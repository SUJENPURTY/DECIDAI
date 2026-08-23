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

from models.schemas import (AnalyzeCaseResponse, HumanDecisionRequest, HumanDecisionResponse, TeamInvitationAcceptRequest,
    TeamInvitationCreateRequest)
from services.document_service import DocumentExtractionError, extract_text
from services.gemini_service import GeminiAnalysisError, analyse_case
from services.database_service import (CaseNotFoundError, DatabaseConfigurationError, DatabaseError, DuplicateDecisionError, InvitationConflictError,
    InvitationEmailMismatchError, InvitationNotFoundError, PermissionDeniedError, accept_organization_invitation, create_audit_log,
    create_case, create_organization_invitation, dashboard_stats, get_case, list_cases, list_organization_invitations,
    revoke_organization_invitation, save_ai_analysis, save_human_decision)
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
        invitation = create_organization_invitation(
            current_user.organization_id, current_user.user_id, request.email,
            request.role, token_hash, expires_at,
        )
        # This structured event deliberately excludes the raw token and hash.
        logger.info("audit_event=TEAM_INVITE_CREATED organization_id=%s invitation_id=%s actor_user_id=%s",
            current_user.organization_id, invitation["id"], current_user.user_id)
        return {"invitation": _invite_response(invitation), "invite_url": _invite_url(raw_token)}
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
        logger.info("audit_event=TEAM_INVITE_ACCEPTED organization_id=%s actor_user_id=%s",
            profile["organization_id"], current_user.user_id)
        return {"organization_id": profile["organization_id"], "role": profile["role"]}
    except InvitationEmailMismatchError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
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
        return HumanDecisionResponse.model_validate(save_human_decision(
            decision_case_id,
            request,
            current_user.organization_id,
            current_user.user_id,
            current_user.role,
        ))
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
