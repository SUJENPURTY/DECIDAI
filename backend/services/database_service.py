"""Centralized, server-side persistence for DECIDAI's human decision audit trail."""
import os
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from supabase import Client, create_client

from models.schemas import AnalysisResult, HumanDecisionRequest


class DatabaseError(RuntimeError):
    """A safe error suitable for the API client."""


class DatabaseConfigurationError(DatabaseError):
    pass


class DuplicateDecisionError(DatabaseError):
    pass


class CaseNotFoundError(DatabaseError):
    pass


class PermissionDeniedError(DatabaseError):
    pass


class InvitationConflictError(DatabaseError):
    pass


class InvitationNotFoundError(DatabaseError):
    pass


class InvitationEmailMismatchError(PermissionDeniedError):
    pass


TEAM_ROLES = {"admin", "reviewer", "requester"}
_EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_INVITATION_COLUMNS = "id,organization_id,email,role,invited_by,expires_at,accepted_at,created_at,updated_at"


def _client() -> Client:
    url = os.getenv("SUPABASE_URL")
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not service_role_key:
        raise DatabaseConfigurationError("Decision storage is not configured yet. Please contact an administrator.")
    return create_client(url, service_role_key)


def _one(response: Any) -> dict[str, Any]:
    rows = response.data or []
    if not rows:
        raise CaseNotFoundError("The requested decision case could not be found.")
    return rows[0] if isinstance(rows, list) else rows


def _amount_as_decimal(amount: str) -> str:
    normalized = re.sub(r"[^0-9.-]", "", amount)
    try:
        return str(Decimal(normalized))
    except (InvalidOperation, ValueError) as exc:
        raise DatabaseError("The request amount must be a valid number.") from exc


def normalize_email(email: str) -> str:
    """Normalize the address used for invitation lookup and storage."""
    normalized = email.strip().lower()
    if not _EMAIL_PATTERN.fullmatch(normalized):
        raise DatabaseError("Please provide a valid invitation email address.")
    return normalized


def _has_rows(response: Any) -> bool:
    return bool(response.data)


def create_organization_invitation(organization_id: str, invited_by: str, email: str,
                                   role: str, token_hash: str, expires_at: datetime) -> dict[str, Any]:
    """Create an invitation after enforcing tenant membership and pending-invite rules."""
    if role not in TEAM_ROLES:
        raise DatabaseError("The invitation role is invalid.")
    if not token_hash or len(token_hash) != 64:
        raise DatabaseError("The invitation token could not be created.")
    normalized_email = normalize_email(email)
    try:
        client = _client()
        member = client.table("profiles").select("id").eq(
            "organization_id", organization_id
        ).ilike("email", normalized_email).limit(1).execute()
        if _has_rows(member):
            raise InvitationConflictError("This user already belongs to this organization.")

        pending = client.table("organization_invitations").select("id").eq(
            "organization_id", organization_id
        ).ilike("email", normalized_email).is_("accepted_at", "null").gt(
            "expires_at", datetime.now(timezone.utc).isoformat()
        ).limit(1).execute()
        if _has_rows(pending):
            raise InvitationConflictError("A pending invitation already exists for this email address.")

        return _one(client.table("organization_invitations").insert({
            "organization_id": organization_id,
            "email": normalized_email,
            "role": role,
            "invited_by": invited_by,
            "token_hash": token_hash,
            "expires_at": expires_at.isoformat(),
        }).select(_INVITATION_COLUMNS).execute())
    except (DatabaseError, InvitationConflictError):
        raise
    except Exception as exc:
        if "organization_invitations_pending_email_key" in str(exc) or "duplicate" in str(exc).lower():
            raise InvitationConflictError("A pending invitation already exists for this email address.") from exc
        raise DatabaseError("We could not create this team invitation. Please try again.") from exc


def list_organization_invitations(organization_id: str) -> list[dict[str, Any]]:
    """Return only token-safe invitation fields for one organization."""
    try:
        return _client().table("organization_invitations").select(_INVITATION_COLUMNS).eq(
            "organization_id", organization_id
        ).order("created_at", desc=True).execute().data or []
    except DatabaseConfigurationError:
        raise
    except Exception as exc:
        raise DatabaseError("We could not retrieve team invitations. Please try again.") from exc


def revoke_organization_invitation(invitation_id: str, organization_id: str) -> None:
    """Delete an unaccepted invitation in the admin's own organization only."""
    try:
        client = _client()
        invitation = client.table("organization_invitations").select("id,accepted_at").eq(
            "id", invitation_id
        ).eq("organization_id", organization_id).limit(1).execute().data or []
        if not invitation:
            raise InvitationNotFoundError("The requested team invitation could not be found.")
        if invitation[0].get("accepted_at"):
            raise InvitationConflictError("Accepted invitations cannot be revoked.")
        client.table("organization_invitations").delete().eq("id", invitation_id).eq(
            "organization_id", organization_id
        ).is_("accepted_at", "null").execute()
    except (DatabaseError, InvitationConflictError, InvitationNotFoundError):
        raise
    except Exception as exc:
        raise DatabaseError("We could not revoke this team invitation. Please try again.") from exc


def accept_organization_invitation(token_hash: str, user_id: str, authenticated_email: str) -> dict[str, Any]:
    """Join the authenticated user to the organization encoded by a valid invite."""
    if not token_hash or len(token_hash) != 64:
        raise InvitationNotFoundError("This invitation is invalid, expired, or has already been used.")
    verified_email = normalize_email(authenticated_email)
    now = datetime.now(timezone.utc).isoformat()
    try:
        client = _client()
        rows = client.table("organization_invitations").select(
            f"{_INVITATION_COLUMNS},token_hash"
        ).eq("token_hash", token_hash).is_("accepted_at", "null").gt(
            "expires_at", now
        ).limit(2).execute().data or []
        if len(rows) != 1:
            raise InvitationNotFoundError("This invitation is invalid, expired, or has already been used.")
        invitation = rows[0]
        if normalize_email(invitation["email"]) != verified_email:
            raise InvitationEmailMismatchError("This invitation is not for the authenticated email address.")
        if invitation.get("role") not in TEAM_ROLES:
            raise InvitationNotFoundError("This invitation is invalid, expired, or has already been used.")

        profile = _one(client.table("profiles").update({
            "organization_id": invitation["organization_id"],
            "role": invitation["role"],
            "email": verified_email,
        }).eq("id", user_id).select("id,organization_id,role,email").execute())
        accepted = client.table("organization_invitations").update({
            "accepted_at": now,
        }).eq("id", invitation["id"]).eq("token_hash", token_hash).is_(
            "accepted_at", "null"
        ).gt("expires_at", now).select(_INVITATION_COLUMNS).execute().data or []
        if not accepted:
            raise InvitationNotFoundError("This invitation is invalid, expired, or has already been used.")
        return profile
    except (DatabaseError, InvitationNotFoundError, InvitationEmailMismatchError):
        raise
    except Exception as exc:
        raise DatabaseError("We could not accept this team invitation. Please try again.") from exc


def create_case(case_id: str, case: dict[str, str], supporting_document_name: str | None,
                organization_id: str, user_id: str, role: str) -> dict[str, Any]:
    if role not in {"admin", "requester"}:
        raise DatabaseError("You do not have permission to create cases.")
    try:
        return _one(_client().table("decision_cases").insert({
            "case_id": case_id, "title": case["title"], "category": case["category"],
            "amount": _amount_as_decimal(case["amount"]), "requester_name": case["requester_name"],
            "department": case["department"], "description": case["description"],
            "supporting_document_name": supporting_document_name,
            # Ownership is always derived from the authenticated backend context.
            "organization_id": organization_id, "created_by": user_id,
        }).execute())
    except DatabaseError:
        raise
    except Exception as exc:
        raise DatabaseError("We could not save this decision case. Please try again.") from exc


def create_audit_log(decision_case_id: str, event_type: str, actor_type: str, details: dict[str, Any],
                     organization_id: str, user_id: str, role: str, actor_name: str | None = None) -> None:
    """Write an audit event only after confirming tenant access to its case."""
    try:
        client = _client()
        case_query = client.table("decision_cases").select("id").eq("id", decision_case_id).eq(
            "organization_id", organization_id
        )
        if role == "requester":
            case_query = case_query.eq("created_by", user_id)
        elif role not in {"admin", "reviewer"}:
            raise CaseNotFoundError("The requested decision case could not be found.")
        verified_case = _one(case_query.execute())
        audit_details = {**details, "actor_user_id": user_id}
        client.table("audit_logs").insert({
            "decision_case_id": verified_case["id"], "organization_id": organization_id,
            "event_type": event_type, "actor_type": actor_type, "actor_name": actor_name,
            "details": audit_details,
        }).execute()
    except (CaseNotFoundError, DatabaseConfigurationError):
        raise
    except Exception as exc:
        raise DatabaseError("We could not record the decision audit event. Please try again.") from exc


def save_ai_analysis(decision_case_id: str, analysis: AnalysisResult, model_name: str,
                     organization_id: str, user_id: str, role: str) -> dict[str, Any]:
    """Persist an analysis only after authorizing its parent case."""
    try:
        client = _client()
        case_query = client.table("decision_cases").select("id").eq("id", decision_case_id).eq(
            "organization_id", organization_id
        )
        if role == "requester":
            case_query = case_query.eq("created_by", user_id)
        elif role not in {"admin", "reviewer"}:
            raise CaseNotFoundError("The requested decision case could not be found.")
        verified_case = _one(case_query.execute())

        row = _one(client.table("ai_analyses").insert({
            "decision_case_id": verified_case["id"], "organization_id": organization_id,
            "recommendation": analysis.recommendation,
            "confidence": analysis.confidence, "summary": analysis.summary, "reasoning": analysis.reasoning,
            "evidence": [item.model_dump() for item in analysis.evidence],
            "risk_flags": [item.model_dump() for item in analysis.risk_flags],
            "missing_information": analysis.missing_information, "human_review_focus": analysis.human_review_focus,
            "analysis_notice": analysis.analysis_notice, "model_name": model_name,
        }).execute())
        create_audit_log(decision_case_id, "AI_ANALYSIS_COMPLETED", "AI", {
            "recommendation": analysis.recommendation, "confidence": analysis.confidence, "model_name": model_name,
        }, organization_id, user_id, role)
        return row
    except DatabaseError:
        raise
    except Exception as exc:
        raise DatabaseError("We could not save the AI analysis. Please try again.") from exc


def _case_with_relations(decision_case_id: str, organization_id: str, user_id: str, role: str) -> dict[str, Any]:
    """Load decision inputs only after the parent case passes tenant authorization."""
    try:
        if role not in {"admin", "reviewer"}:
            raise PermissionDeniedError("You do not have permission to submit a final decision.")
        client = _client()
        record = _one(client.table("decision_cases").select("*").eq("id", decision_case_id).eq(
            "organization_id", organization_id
        ).execute())
        record["ai_analyses"] = client.table("ai_analyses").select("*").eq(
            "decision_case_id", record["id"]
        ).execute().data or []
        record["human_decisions"] = client.table("human_decisions").select("*").eq(
            "decision_case_id", record["id"]
        ).execute().data or []
        return record
    except (DatabaseError, PermissionDeniedError):
        raise
    except Exception as exc:
        raise DatabaseError("We could not retrieve this decision case. Please try again.") from exc


def get_case(decision_case_id: str, organization_id: str, user_id: str, role: str) -> dict[str, Any]:
    """Return a case only when it belongs to the authenticated user's tenant.

    The parent case is authorized before any related records are requested so an
    inaccessible case is indistinguishable from a nonexistent one.
    """
    try:
        query = _client().table("decision_cases").select("*").eq("id", decision_case_id).eq(
            "organization_id", organization_id
        )
        if role == "requester":
            query = query.eq("created_by", user_id)
        elif role not in {"admin", "reviewer"}:
            raise CaseNotFoundError("The requested decision case could not be found.")

        case = _one(query.execute())
        client = _client()
        case["ai_analyses"] = client.table("ai_analyses").select("*").eq(
            "decision_case_id", case["id"]
        ).execute().data or []
        case["human_decisions"] = client.table("human_decisions").select("*").eq(
            "decision_case_id", case["id"]
        ).execute().data or []
        case["audit_logs"] = client.table("audit_logs").select("*").eq(
            "decision_case_id", case["id"]
        ).execute().data or []
        return case
    except (CaseNotFoundError, DatabaseConfigurationError):
        raise
    except Exception as exc:
        raise DatabaseError("We could not retrieve this decision case. Please try again.") from exc


def save_human_decision(decision_case_id: str, request: HumanDecisionRequest,
                        organization_id: str, user_id: str, role: str) -> dict[str, Any]:
    record = _case_with_relations(decision_case_id, organization_id, user_id, role)
    if record.get("human_decisions"):
        raise DuplicateDecisionError("This case already has a final human decision.")
    analyses = record.get("ai_analyses") or []
    if not analyses:
        raise DatabaseError("This case has no AI analysis to review.")
    analysis = sorted(analyses, key=lambda item: item["created_at"])[-1]
    is_override = (analysis["recommendation"] == "APPROVE" and request.final_decision == "REJECTED") or (
        analysis["recommendation"] == "REJECT" and request.final_decision == "APPROVED"
    )
    try:
        row = _one(_client().table("human_decisions").insert({
            "decision_case_id": record["id"], "organization_id": organization_id, "ai_analysis_id": analysis["id"],
            "final_decision": request.final_decision, "decision_reason": request.decision_reason.strip(),
            "reviewer_name": request.reviewer_name.strip(), "is_override": is_override,
        }).execute())
        _client().table("decision_cases").update({"status": request.final_decision}).eq("id", record["id"]).eq(
            "organization_id", organization_id
        ).execute()
        create_audit_log(record["id"], "HUMAN_DECISION_SUBMITTED", "HUMAN", {
            "final_decision": request.final_decision, "is_override": is_override,
        }, organization_id, user_id, role, request.reviewer_name.strip())
        if is_override:
            create_audit_log(record["id"], "HUMAN_OVERRIDE", "HUMAN", {
                "ai_recommendation": analysis["recommendation"], "human_decision": request.final_decision,
            }, organization_id, user_id, role, request.reviewer_name.strip())
        return row
    except (DuplicateDecisionError, CaseNotFoundError, PermissionDeniedError):
        raise
    except Exception as exc:
        if "duplicate" in str(exc).lower() or "23505" in str(exc):
            raise DuplicateDecisionError("This case already has a final human decision.") from exc
        raise DatabaseError("We could not record the final human decision. Please try again.") from exc


def list_cases(organization_id: str, user_id: str, role: str, limit: int | None = None) -> list[dict[str, Any]]:
    try:
        query = _client().table("decision_cases").select("*,ai_analyses(*),human_decisions(*)").eq(
            "organization_id", organization_id
        ).order("created_at", desc=True)
        if role == "requester":
            query = query.eq("created_by", user_id)
        if limit:
            query = query.limit(limit)
        return query.execute().data or []
    except DatabaseConfigurationError:
        raise
    except Exception as exc:
        raise DatabaseError("We could not retrieve decision history. Please try again.") from exc


def _extract_human_decision(case: object) -> dict[str, Any] | None:
    """Normalize Supabase's embedded relation without treating primitives as records."""
    if not isinstance(case, dict):
        return None
    value = case.get("human_decisions")
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                return item
    return None


def dashboard_stats(organization_id: str, user_id: str, role: str) -> dict[str, int]:
    rows = [row for row in list_cases(organization_id, user_id, role) if isinstance(row, dict)]
    decisions = [_extract_human_decision(row) for row in rows]
    return {
        "total_cases": len(rows),
        "pending_review": sum(row.get("status") == "PENDING_HUMAN_REVIEW" for row in rows),
        "approved": sum(row.get("status") == "APPROVED" for row in rows),
        "rejected": sum(row.get("status") == "REJECTED" for row in rows),
        "human_overrides": sum(decision is not None and decision.get("is_override") is True for decision in decisions),
    }
