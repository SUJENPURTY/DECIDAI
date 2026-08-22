"""Centralized, server-side persistence for DECIDAI's human decision audit trail."""
import os
import re
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


def create_case(case_id: str, case: dict[str, str], supporting_document_name: str | None) -> dict[str, Any]:
    try:
        return _one(_client().table("decision_cases").insert({
            "case_id": case_id, "title": case["title"], "category": case["category"],
            "amount": _amount_as_decimal(case["amount"]), "requester_name": case["requester_name"],
            "department": case["department"], "description": case["description"],
            "supporting_document_name": supporting_document_name,
        }).execute())
    except DatabaseError:
        raise
    except Exception as exc:
        raise DatabaseError("We could not save this decision case. Please try again.") from exc


def create_audit_log(decision_case_id: str, event_type: str, actor_type: str, details: dict[str, Any], actor_name: str | None = None) -> None:
    try:
        _client().table("audit_logs").insert({"decision_case_id": decision_case_id, "event_type": event_type,
            "actor_type": actor_type, "actor_name": actor_name, "details": details}).execute()
    except Exception as exc:
        raise DatabaseError("We could not record the decision audit event. Please try again.") from exc


def save_ai_analysis(decision_case_id: str, analysis: AnalysisResult, model_name: str) -> dict[str, Any]:
    try:
        row = _one(_client().table("ai_analyses").insert({
            "decision_case_id": decision_case_id, "recommendation": analysis.recommendation,
            "confidence": analysis.confidence, "summary": analysis.summary, "reasoning": analysis.reasoning,
            "evidence": [item.model_dump() for item in analysis.evidence],
            "risk_flags": [item.model_dump() for item in analysis.risk_flags],
            "missing_information": analysis.missing_information, "human_review_focus": analysis.human_review_focus,
            "analysis_notice": analysis.analysis_notice, "model_name": model_name,
        }).execute())
        create_audit_log(decision_case_id, "AI_ANALYSIS_COMPLETED", "AI", {
            "recommendation": analysis.recommendation, "confidence": analysis.confidence, "model_name": model_name,
        })
        return row
    except DatabaseError:
        raise
    except Exception as exc:
        raise DatabaseError("We could not save the AI analysis. Please try again.") from exc


def _case_with_relations(decision_case_id: str) -> dict[str, Any]:
    try:
        return _one(_client().table("decision_cases").select(
            "*,ai_analyses(*),human_decisions(*),audit_logs(*)"
        ).eq("id", decision_case_id).execute())
    except DatabaseError:
        raise
    except Exception as exc:
        raise DatabaseError("We could not retrieve this decision case. Please try again.") from exc


def get_case(decision_case_id: str) -> dict[str, Any]:
    return _case_with_relations(decision_case_id)


def save_human_decision(decision_case_id: str, request: HumanDecisionRequest) -> dict[str, Any]:
    record = _case_with_relations(decision_case_id)
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
            "decision_case_id": decision_case_id, "ai_analysis_id": analysis["id"],
            "final_decision": request.final_decision, "decision_reason": request.decision_reason.strip(),
            "reviewer_name": request.reviewer_name.strip(), "is_override": is_override,
        }).execute())
        _client().table("decision_cases").update({"status": request.final_decision}).eq("id", decision_case_id).execute()
        create_audit_log(decision_case_id, "HUMAN_DECISION_SUBMITTED", "HUMAN", {
            "final_decision": request.final_decision, "is_override": is_override,
        }, request.reviewer_name.strip())
        if is_override:
            create_audit_log(decision_case_id, "HUMAN_OVERRIDE", "HUMAN", {
                "ai_recommendation": analysis["recommendation"], "human_decision": request.final_decision,
            }, request.reviewer_name.strip())
        return row
    except DuplicateDecisionError:
        raise
    except Exception as exc:
        if "duplicate" in str(exc).lower() or "23505" in str(exc):
            raise DuplicateDecisionError("This case already has a final human decision.") from exc
        raise DatabaseError("We could not record the final human decision. Please try again.") from exc


def list_cases(limit: int | None = None) -> list[dict[str, Any]]:
    try:
        query = _client().table("decision_cases").select("*,ai_analyses(*),human_decisions(*)").order("created_at", desc=True)
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


def dashboard_stats() -> dict[str, int]:
    rows = [row for row in list_cases() if isinstance(row, dict)]
    decisions = [_extract_human_decision(row) for row in rows]
    return {
        "total_cases": len(rows),
        "pending_review": sum(row.get("status") == "PENDING_HUMAN_REVIEW" for row in rows),
        "approved": sum(row.get("status") == "APPROVED" for row in rows),
        "rejected": sum(row.get("status") == "REJECTED" for row in rows),
        "human_overrides": sum(decision is not None and decision.get("is_override") is True for decision in decisions),
    }
