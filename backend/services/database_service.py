"""Centralized, server-side persistence for DECIDAI's human decision audit trail."""
import os
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from supabase import Client, create_client

from models.schemas import AnalysisResult, HumanDecisionRequest
from services.plan_limits import PLAN_LIMITS, billing_enforcement_enabled, limits_for, normalized_plan


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


class TeamMemberConflictError(DatabaseError):
    pass


class TeamMemberNotFoundError(DatabaseError):
    pass


class PlanLimitExceededError(PermissionDeniedError):
    def __init__(self, limit_type: str):
        super().__init__("Your workspace has reached its plan limit. Upgrade is required to continue.")
        self.limit_type = limit_type


TEAM_ROLES = {"admin", "reviewer", "requester"}
_EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_INVITATION_COLUMNS = "id,organization_id,email,role,invited_by,expires_at,accepted_at,created_at,updated_at"
_SUBSCRIPTION_COLUMNS = (
    "organization_id,plan,billing_status,provider,provider_customer_id,provider_subscription_id,"
    "current_period_start,current_period_end,cancel_at_period_end,created_at,updated_at"
)


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


def invitation_email_context(organization_id: str, invited_by: str) -> dict[str, str]:
    """Load trusted display names for the invitation email without exposing credentials."""
    try:
        client = _client()
        organization = _one(client.table("organizations").select("name").eq("id", organization_id).execute())
        inviter = _one(client.table("profiles").select("full_name,email").eq("id", invited_by).eq(
            "organization_id", organization_id
        ).execute())
        return {
            "workspace_name": organization.get("name") or "DECIDAI Workspace",
            "inviter_name": inviter.get("full_name") or inviter.get("email") or "A DECIDAI administrator",
        }
    except DatabaseError:
        raise
    except Exception as exc:
        raise DatabaseError("We could not prepare this invitation email.") from exc


def _manage_organization_member(organization_id: str, actor_user_id: str, target_user_id: str,
                                action: str, new_role: str | None = None) -> dict[str, Any]:
    if action == "change_role" and new_role not in TEAM_ROLES:
        raise DatabaseError("The member role is invalid.")
    try:
        result = _client().rpc("manage_organization_member", {
            "p_actor_user_id": actor_user_id,
            "p_target_user_id": target_user_id,
            "p_action": action,
            "p_new_role": new_role,
        }).execute()
        rows = result.data or []
        if not rows:
            raise TeamMemberNotFoundError("The requested workspace member could not be found.")
        member = rows[0]
        if str(member.get("organization_id")) != str(organization_id):
            raise TeamMemberNotFoundError("The requested workspace member could not be found.")
        return member
    except (DatabaseError, TeamMemberConflictError, TeamMemberNotFoundError):
        raise
    except Exception as exc:
        message = str(exc).lower()
        if "last workspace admin" in message:
            raise TeamMemberConflictError("The last workspace admin cannot be changed or removed.") from exc
        if "could not be found" in message:
            raise TeamMemberNotFoundError("The requested workspace member could not be found.") from exc
        if "only workspace administrators" in message:
            raise PermissionDeniedError("You do not have permission for this action.") from exc
        raise DatabaseError("We could not update this workspace member. Please try again.") from exc


def change_organization_member_role(organization_id: str, actor_user_id: str,
                                    target_user_id: str, new_role: str) -> dict[str, Any]:
    return _manage_organization_member(organization_id, actor_user_id, target_user_id, "change_role", new_role)


def remove_organization_member(organization_id: str, actor_user_id: str, target_user_id: str) -> dict[str, Any]:
    return _manage_organization_member(organization_id, actor_user_id, target_user_id, "remove")


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

        ensure_organization_plan_limits(invitation["organization_id"], ("team_members",))

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


def create_organization_notification(organization_id: str, event_type: str, title: str, body: str,
                                     visible_to_roles: list[str] | None = None,
                                     recipient_user_id: str | None = None,
                                     decision_case_id: str | None = None,
                                     details: dict[str, Any] | None = None) -> None:
    """Persist a token-safe in-app notification through the trusted backend client."""
    allowed_events = {
        "CASE_CREATED", "AI_ANALYSIS_COMPLETED", "HUMAN_DECISION_SUBMITTED",
        "TEAM_INVITE_CREATED", "TEAM_INVITE_ACCEPTED",
        "TEAM_MEMBER_ROLE_CHANGED", "TEAM_MEMBER_REMOVED",
    }
    roles = visible_to_roles or []
    if event_type not in allowed_events or any(role not in TEAM_ROLES for role in roles):
        raise DatabaseError("The notification could not be recorded.")
    if not recipient_user_id and not roles:
        raise DatabaseError("The notification must have an audience.")
    try:
        _client().table("organization_notifications").insert({
            "organization_id": organization_id,
            "event_type": event_type,
            "title": title,
            "body": body,
            "visible_to_roles": roles,
            "recipient_user_id": recipient_user_id,
            "decision_case_id": decision_case_id,
            "details": details or {},
        }).execute()
    except DatabaseConfigurationError:
        raise
    except Exception as exc:
        raise DatabaseError("The notification could not be recorded.") from exc


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
        row["case_owner_id"] = record.get("created_by")
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


def _organization_count(table: str, organization_id: str, event_type: str | None = None,
                        created_since: str | None = None) -> int:
    query = _client().table(table).select("id", count="exact", head=True).eq(
        "organization_id", organization_id
    )
    if event_type:
        query = query.eq("event_type", event_type)
    if created_since:
        query = query.gte("created_at", created_since)
    response = query.execute()
    return int(response.count or 0)


def organization_usage(organization_id: str) -> dict[str, int]:
    """Return organization-wide usage using source-of-truth records, not mutable counters."""
    try:
        return {
            "cases_created": _organization_count("decision_cases", organization_id),
            "ai_analyses": _organization_count("ai_analyses", organization_id),
            "human_decisions": _organization_count("human_decisions", organization_id),
            "team_members": _organization_count("profiles", organization_id),
            "invitations_sent": _organization_count(
                "organization_usage_events", organization_id, "INVITATION_SENT"
            ),
        }
    except DatabaseConfigurationError:
        raise
    except Exception as exc:
        raise DatabaseError("We could not retrieve organization usage. Please try again.") from exc


def _month_start() -> str:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()


def _organization_plan(organization_id: str) -> str:
    try:
        organization = _one(_client().table("organizations").select("plan").eq(
            "id", organization_id
        ).execute())
        return normalized_plan(organization.get("plan"))
    except (DatabaseError, DatabaseConfigurationError):
        raise
    except Exception as exc:
        raise DatabaseError("We could not retrieve the workspace plan. Please try again.") from exc


def organization_plan_usage(organization_id: str) -> dict[str, int]:
    """Return current-calendar-month usage plus the active membership count."""
    try:
        month_start = _month_start()
        return {
            "cases_created": _organization_count("decision_cases", organization_id, created_since=month_start),
            "ai_analyses": _organization_count("ai_analyses", organization_id, created_since=month_start),
            "team_members": _organization_count("profiles", organization_id),
            "invitations_sent": _organization_count(
                "organization_usage_events", organization_id, "INVITATION_SENT", month_start
            ),
        }
    except DatabaseConfigurationError:
        raise
    except Exception as exc:
        raise DatabaseError("We could not retrieve current plan usage. Please try again.") from exc


def organization_billing_plan(organization_id: str) -> dict[str, Any]:
    plan = _organization_plan(organization_id)
    limits = limits_for(plan)
    current_usage = organization_plan_usage(organization_id)
    remaining_usage = {
        metric: None if limit is None else max(limit - current_usage[metric], 0)
        for metric, limit in limits.items()
    }
    return {
        "plan": plan,
        "limits": limits,
        "current_usage": current_usage,
        "remaining_usage": remaining_usage,
    }


def get_organization_subscription(organization_id: str) -> dict[str, Any]:
    """Return a subscription only for the already-authenticated caller's organization."""
    try:
        rows = _client().table("organization_subscriptions").select(_SUBSCRIPTION_COLUMNS).eq(
            "organization_id", organization_id
        ).limit(1).execute().data or []
        if not rows:
            raise DatabaseError("Billing is not initialized for this workspace yet.")
        return rows[0]
    except DatabaseError:
        raise
    except Exception as exc:
        raise DatabaseError("We could not retrieve the workspace subscription. Please try again.") from exc


def checkout_not_configured(organization_id: str, target_plan: str) -> dict[str, Any]:
    """Validate a paid target without creating a checkout session or changing a plan."""
    if target_plan not in {"PRO", "BUSINESS"}:
        raise DatabaseError("The requested upgrade plan is invalid.")
    return {
        "status": "payment_not_configured",
        "target_plan": target_plan,
        "current_plan": _organization_plan(organization_id),
    }


def apply_organization_subscription_change(
    organization_id: str, plan: str, billing_status: str, provider: str,
    provider_customer_id: str | None = None, provider_subscription_id: str | None = None,
    current_period_start: datetime | None = None, current_period_end: datetime | None = None,
    cancel_at_period_end: bool = False,
) -> dict[str, Any]:
    """Trusted backend-only plan mutation for a future verified provider webhook."""
    allowed_statuses = {"free", "pending", "active", "past_due", "canceled"}
    if plan not in PLAN_LIMITS or billing_status not in allowed_statuses or not provider.strip():
        raise DatabaseError("The subscription update is invalid.")
    try:
        client = _client()
        # The organization is supplied only by trusted server-side webhook mapping, never a client request.
        _one(client.table("organizations").update({"plan": plan}).eq("id", organization_id).select("id").execute())
        payload = {
            "organization_id": organization_id,
            "plan": plan,
            "billing_status": billing_status,
            "provider": provider.strip(),
            "provider_customer_id": provider_customer_id,
            "provider_subscription_id": provider_subscription_id,
            "current_period_start": current_period_start.isoformat() if current_period_start else None,
            "current_period_end": current_period_end.isoformat() if current_period_end else None,
            "cancel_at_period_end": cancel_at_period_end,
        }
        return _one(client.table("organization_subscriptions").upsert(
            payload, on_conflict="organization_id"
        ).select(_SUBSCRIPTION_COLUMNS).execute())
    except DatabaseError:
        raise
    except Exception as exc:
        raise DatabaseError("We could not apply the subscription update. Please try again.") from exc


def _pending_invitation_count(organization_id: str) -> int:
    response = _client().table("organization_invitations").select(
        "id", count="exact", head=True
    ).eq("organization_id", organization_id).is_("accepted_at", "null").gt(
        "expires_at", datetime.now(timezone.utc).isoformat()
    ).execute()
    return int(response.count or 0)


def ensure_organization_plan_limits(organization_id: str, limit_types: tuple[str, ...],
                                    reserve_team_seat: bool = False) -> None:
    """Raise a safe error before a paid-plan-limited action is performed."""
    if not billing_enforcement_enabled():
        return
    plan = _organization_plan(organization_id)
    limits = limits_for(plan)
    usage = organization_plan_usage(organization_id)
    for limit_type in limit_types:
        limit = limits.get(limit_type)
        if limit is None:
            continue
        current = usage[limit_type]
        if limit_type == "team_members" and reserve_team_seat:
            current += _pending_invitation_count(organization_id)
        if current + 1 > limit:
            raise PlanLimitExceededError(limit_type)


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


def _latest_relation(value: object) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        records = [item for item in value if isinstance(item, dict)]
        if records:
            return max(records, key=lambda item: str(item.get("created_at") or ""))
    return None


def organization_analytics(organization_id: str) -> dict[str, Any]:
    """Derived admin analytics from tenant-scoped decision records; no counters required."""
    try:
        cases = list_cases(organization_id, "", "admin")
        decisions_by_outcome = {"APPROVED": 0, "REJECTED": 0}
        comparisons: dict[tuple[str, str], int] = {}
        confidences: list[float] = []
        now = datetime.now(timezone.utc).date()
        days = [(now - timedelta(days=offset)) for offset in range(13, -1, -1)]
        case_counts = {day.isoformat(): 0 for day in days}

        for case in cases:
            created_at = str(case.get("created_at") or "")
            try:
                created_day = datetime.fromisoformat(created_at.replace("Z", "+00:00")).date().isoformat()
                if created_day in case_counts:
                    case_counts[created_day] += 1
            except ValueError:
                pass
            analysis = _latest_relation(case.get("ai_analyses"))
            decision = _latest_relation(case.get("human_decisions"))
            if analysis and isinstance(analysis.get("confidence"), (int, float)):
                confidences.append(float(analysis["confidence"]))
            if decision and decision.get("final_decision") in decisions_by_outcome:
                outcome = decision["final_decision"]
                decisions_by_outcome[outcome] += 1
                if analysis and analysis.get("recommendation"):
                    key = (str(analysis["recommendation"]), str(outcome))
                    comparisons[key] = comparisons.get(key, 0) + 1

        stats = dashboard_stats(organization_id, "", "admin")
        usage = organization_usage(organization_id)
        finalized = decisions_by_outcome["APPROVED"] + decisions_by_outcome["REJECTED"]
        return {
            "overview": {
                **stats,
                "ai_analyses": usage["ai_analyses"],
                "team_members": usage["team_members"],
                "invitations_sent": usage["invitations_sent"],
                "approval_rate": round((decisions_by_outcome["APPROVED"] / finalized) * 100, 1) if finalized else 0,
                "average_ai_confidence": round(sum(confidences) / len(confidences), 1) if confidences else 0,
            },
            "cases_over_time": [
                {"date": day, "count": case_counts[day]}
                for day in case_counts
            ],
            "decisions_by_outcome": decisions_by_outcome,
            "ai_recommendation_vs_human_decision": [
                {"recommendation": recommendation, "decision": decision, "count": count}
                for (recommendation, decision), count in sorted(comparisons.items())
            ],
        }
    except DatabaseConfigurationError:
        raise
    except Exception as exc:
        raise DatabaseError("We could not retrieve organization analytics. Please try again.") from exc
