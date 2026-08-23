import os
import logging
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlencode

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from models.schemas import (AnalyzeCaseResponse, BillingCheckoutRequest, HumanDecisionRequest, HumanDecisionResponse, TeamInvitationAcceptRequest,
    TeamInvitationCreateRequest, TeamMemberRoleRequest)
from services.document_service import DocumentExtractionError, extract_text
from services.gemini_service import GeminiAnalysisError, analyse_case
from services.email_service import send_team_invitation_email
from services.database_service import (CaseNotFoundError, DatabaseConfigurationError, DatabaseError, DuplicateDecisionError, InvitationConflictError,
    InvitationEmailMismatchError, InvitationNotFoundError, PermissionDeniedError, accept_organization_invitation, create_audit_log,
    create_case, create_organization_invitation, dashboard_stats, ensure_organization_plan_limits, invitation_email_context, get_case, list_cases, list_organization_invitations,
    revoke_organization_invitation, save_ai_analysis, save_human_decision, TeamMemberConflictError, TeamMemberNotFoundError,
    change_organization_member_role, checkout_not_configured, create_organization_notification, get_organization_subscription,
    organization_analytics, organization_billing_plan, organization_usage, PlanLimitExceededError, remove_organization_member)
from services.auth_service import CurrentUser, require_role, require_user

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv(Path(__file__).with_name(".env"))

# Log configuration presence only: credentials must never appear in logs.
logger.info("Gemini API key loaded: %s", "yes" if os.getenv("GEMINI_API_KEY") else "no")
logger.info("Gemini model: %s", os.getenv("GEMINI_MODEL") or "not configured")

app = FastAPI(title="DECIDAI API", version="0.2.0")
origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:5174,http://127.0.0.1:5174",
    ).split(",")
]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


def _invite_url(token: str) -> str:
    base_url = os.getenv("INVITE_BASE_URL", "http://localhost:5173").rstrip("/")
    return f"{base_url}/accept-invite?{urlencode({'token': token})}"


def _invite_status(invitation: dict) -> str:
    if invitation.get("accepted_at"):
        return "accepted"
    expires_at = invitation.get("expires_at")
    if expires_at:
        try:
            if datetime.fromisoformat(expires_at.replace("Z", "+00:00")) <= datetime.now(timezone.utc):
                return "expired"
        except (TypeError, ValueError):
            logger.warning("Invitation %s has an unreadable expiry timestamp.", invitation.get("id"))
    return "pending"


def _invite_response(invitation: dict) -> dict:
    return {**invitation, "status": _invite_status(invitation)}


def _notify_safely(organization_id: str, event_type: str, title: str, body: str,
                   visible_to_roles: list[str] | None = None, recipient_user_id: str | None = None,
                   decision_case_id: str | None = None, details: dict | None = None) -> None:
    """Notifications must never interrupt an already-successful DECIDAI workflow."""
    try:
        create_organization_notification(
            organization_id, event_type, title, body, visible_to_roles,
            recipient_user_id, decision_case_id, details,
        )
    except DatabaseError:
        logger.warning("notification_event=%s organization_id=%s was not persisted", event_type, organization_id)


def _plan_limit_error(exc: PlanLimitExceededError) -> HTTPException:
    return HTTPException(status_code=403, detail={
        "code": "PLAN_LIMIT_REACHED",
        "limit_type": exc.limit_type,
        "upgrade_required": True,
        "message": str(exc),
    })


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/team/invitations", status_code=201)
def create_team_invitation(request: TeamInvitationCreateRequest,
    current_user: CurrentUser = Depends(require_role("admin"))) -> dict:
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    try:
        ensure_organization_plan_limits(
            current_user.organization_id, ("invitations_sent", "team_members"), reserve_team_seat=True,
        )
        invitation = create_organization_invitation(
            current_user.organization_id, current_user.user_id, request.email,
            request.role, token_hash, expires_at,
        )
        invite_url = _invite_url(raw_token)
        delivery_status = "failed"
        try:
            context = invitation_email_context(current_user.organization_id, current_user.user_id)
            delivery_status = send_team_invitation_email(
                recipient=invitation["email"], inviter_name=context["inviter_name"],
                workspace_name=context["workspace_name"], role=invitation["role"], invite_url=invite_url,
            ).status
        except DatabaseError:
            logger.warning("Invitation email context could not be loaded for invitation_id=%s", invitation["id"])
        if delivery_status != "sent":
            logger.warning("Invitation email delivery status=%s invitation_id=%s", delivery_status, invitation["id"])
        _notify_safely(
            current_user.organization_id, "TEAM_INVITE_CREATED", "Team invitation created",
            "A workspace invitation was created for a new member.", ["admin"],
            details={"invitation_id": invitation["id"], "role": invitation["role"]},
        )
        # This structured event deliberately excludes the raw token and hash.
        logger.info("audit_event=TEAM_INVITE_CREATED organization_id=%s invitation_id=%s actor_user_id=%s",
            current_user.organization_id, invitation["id"], current_user.user_id)
        return {"invitation": _invite_response(invitation), "invite_url": invite_url, "email_delivery": delivery_status}
    except PlanLimitExceededError as exc:
        raise _plan_limit_error(exc) from exc
    except InvitationConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DatabaseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/team/invitations")
def get_team_invitations(current_user: CurrentUser = Depends(require_role("admin"))) -> list[dict]:
    try:
        return [_invite_response(invitation) for invitation in list_organization_invitations(current_user.organization_id)]
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DatabaseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.patch("/api/team/members/{user_id}/role")
def change_team_member_role(user_id: str, request: TeamMemberRoleRequest,
    current_user: CurrentUser = Depends(require_role("admin"))) -> dict:
    try:
        result = change_organization_member_role(
            current_user.organization_id, current_user.user_id, user_id, request.role,
        )
        _notify_safely(
            current_user.organization_id, "TEAM_MEMBER_ROLE_CHANGED", "Member role changed",
            "A workspace member's role was updated.", ["admin"],
            details={"target_user_id": user_id, "old_role": result.get("old_role"), "new_role": result.get("new_role")},
        )
        return result
    except TeamMemberNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TeamMemberConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DatabaseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.delete("/api/team/members/{user_id}")
def remove_team_member(user_id: str,
    current_user: CurrentUser = Depends(require_role("admin"))) -> dict:
    try:
        result = remove_organization_member(current_user.organization_id, current_user.user_id, user_id)
        _notify_safely(
            current_user.organization_id, "TEAM_MEMBER_REMOVED", "Member removed",
            "A member was removed from this workspace.", ["admin"],
            details={"target_user_id": user_id, "old_role": result.get("old_role")},
        )
        return result
    except TeamMemberNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TeamMemberConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DatabaseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/team/invitations/{invitation_id}/revoke", status_code=204)
def revoke_team_invitation(invitation_id: str,
    current_user: CurrentUser = Depends(require_role("admin"))) -> None:
    try:
        revoke_organization_invitation(invitation_id, current_user.organization_id)
        logger.info("audit_event=TEAM_INVITE_REVOKED organization_id=%s invitation_id=%s actor_user_id=%s",
            current_user.organization_id, invitation_id, current_user.user_id)
    except InvitationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvitationConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DatabaseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/team/invitations/accept")
def accept_team_invitation(request: TeamInvitationAcceptRequest,
    current_user: CurrentUser = Depends(require_user)) -> dict:
    token_hash = hashlib.sha256(request.token.encode("utf-8")).hexdigest()
    try:
        profile = accept_organization_invitation(token_hash, current_user.user_id, current_user.email)
        _notify_safely(
            profile["organization_id"], "TEAM_INVITE_ACCEPTED", "Team invitation accepted",
            "A new member joined this workspace.", ["admin"],
            details={"role": profile["role"]},
        )
        logger.info("audit_event=TEAM_INVITE_ACCEPTED organization_id=%s actor_user_id=%s",
            profile["organization_id"], current_user.user_id)
        return {"organization_id": profile["organization_id"], "role": profile["role"]}
    except InvitationEmailMismatchError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PlanLimitExceededError as exc:
        raise _plan_limit_error(exc) from exc
    except InvitationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DatabaseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/analyze-case", response_model=AnalyzeCaseResponse)
async def analyze_case(
    title: str = Form(...), category: str = Form(...), amount: str = Form(...),
    requester_name: str = Form(...), department: str = Form(...), description: str = Form(...),
    supporting_document: UploadFile | None = File(default=None),
    current_user: CurrentUser = Depends(require_role("admin", "requester")),
) -> AnalyzeCaseResponse:
    fields = {"title": title, "category": category, "amount": amount, "requester_name": requester_name, "department": department, "description": description}
    if any(not value.strip() for value in fields.values()):
        raise HTTPException(status_code=422, detail="Please complete all required case fields before analysis.")

    try:
        ensure_organization_plan_limits(current_user.organization_id, ("cases_created", "ai_analyses"))
    except PlanLimitExceededError as exc:
        raise _plan_limit_error(exc) from exc
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DatabaseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    document_text, notice = None, None
    supporting_document_name = None
    if supporting_document:
        supporting_document_name = supporting_document.filename
        content = await supporting_document.read()
        try:
            document_text, notice = extract_text(supporting_document.filename, content)
        except DocumentExtractionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        analysis = analyse_case(fields, document_text, notice)
    except GeminiAnalysisError as exc:
        logger.error("Gemini analysis failed [%s]: %s", exc.category, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    case_id = f"DEC-{uuid4().hex[:6].upper()}"
    try:
        decision_case = create_case(case_id, fields, supporting_document_name,
            current_user.organization_id, current_user.user_id, current_user.role)
        create_audit_log(
            decision_case["id"], "CASE_CREATED", "SYSTEM", {"case_id": case_id},
            current_user.organization_id, current_user.user_id, current_user.role,
        )
        ai_analysis = save_ai_analysis(
            decision_case["id"],
            analysis,
            os.getenv("GEMINI_MODEL", "unknown"),
            current_user.organization_id,
            current_user.user_id,
            current_user.role,
        )
        requester_recipient = current_user.user_id if current_user.role == "requester" else None
        _notify_safely(
            current_user.organization_id, "CASE_CREATED", "New decision case",
            "A decision case was created and is ready for review.", ["admin", "reviewer"],
            requester_recipient, decision_case["id"], {"case_id": case_id},
        )
        _notify_safely(
            current_user.organization_id, "AI_ANALYSIS_COMPLETED", "AI analysis completed",
            "AI analysis is ready for a human review.", ["admin", "reviewer"],
            requester_recipient, decision_case["id"], {"case_id": case_id},
        )
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DatabaseError as exc:
        logger.error("Decision persistence failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return AnalyzeCaseResponse(decision_case_id=decision_case["id"], ai_analysis_id=ai_analysis["id"],
        case_id=case_id, case=fields, analysis=analysis)


@app.post("/api/cases/{decision_case_id}/decision", response_model=HumanDecisionResponse)
def submit_human_decision(decision_case_id: str, request: HumanDecisionRequest,
    current_user: CurrentUser = Depends(require_role("admin", "reviewer"))) -> HumanDecisionResponse:
    try:
        result = save_human_decision(
            decision_case_id,
            request,
            current_user.organization_id,
            current_user.user_id,
            current_user.role,
        )
        _notify_safely(
            current_user.organization_id, "HUMAN_DECISION_SUBMITTED", "Human decision submitted",
            "A final human decision was recorded for a case.", ["admin", "reviewer"],
            result.get("case_owner_id"), decision_case_id,
            {"final_decision": result.get("final_decision")},
        )
        return HumanDecisionResponse.model_validate(result)
    except DuplicateDecisionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DatabaseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/cases")
def get_cases(current_user: CurrentUser = Depends(require_user)) -> list[dict]:
    try:
        return list_cases(current_user.organization_id, current_user.user_id, current_user.role)
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DatabaseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/cases/{decision_case_id}")
def get_case_details(decision_case_id: str, current_user: CurrentUser = Depends(require_user)) -> dict:
    try:
        return get_case(
            decision_case_id,
            current_user.organization_id,
            current_user.user_id,
            current_user.role,
        )
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DatabaseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/dashboard/stats")
def get_dashboard_stats(current_user: CurrentUser = Depends(require_user)) -> dict[str, int]:
    try:
        return dashboard_stats(current_user.organization_id, current_user.user_id, current_user.role)
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DatabaseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/usage")
def get_usage(current_user: CurrentUser = Depends(require_role("admin"))) -> dict[str, int]:
    try:
        return organization_usage(current_user.organization_id)
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DatabaseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/analytics")
def get_analytics(current_user: CurrentUser = Depends(require_role("admin"))) -> dict:
    try:
        return organization_analytics(current_user.organization_id)
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DatabaseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/billing/plan")
def get_billing_plan(current_user: CurrentUser = Depends(require_role("admin"))) -> dict:
    try:
        return organization_billing_plan(current_user.organization_id)
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DatabaseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/billing/subscription")
def get_billing_subscription(current_user: CurrentUser = Depends(require_role("admin"))) -> dict:
    try:
        return get_organization_subscription(current_user.organization_id)
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DatabaseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/billing/checkout")
def start_billing_checkout(request: BillingCheckoutRequest,
    current_user: CurrentUser = Depends(require_role("admin"))) -> dict:
    try:
        # Checkout remains deliberately disabled until a provider adapter and verified webhook exist.
        return checkout_not_configured(current_user.organization_id, request.target_plan)
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DatabaseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
