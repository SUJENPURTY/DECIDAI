import os
import logging
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from models.schemas import AnalyzeCaseResponse, HumanDecisionRequest, HumanDecisionResponse
from services.document_service import DocumentExtractionError, extract_text
from services.gemini_service import GeminiAnalysisError, analyse_case
from services.database_service import (CaseNotFoundError, DatabaseConfigurationError, DatabaseError, DuplicateDecisionError,
    create_audit_log, create_case, dashboard_stats, get_case, list_cases, save_ai_analysis, save_human_decision)

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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/analyze-case", response_model=AnalyzeCaseResponse)
async def analyze_case(
    title: str = Form(...), category: str = Form(...), amount: str = Form(...),
    requester_name: str = Form(...), department: str = Form(...), description: str = Form(...),
    supporting_document: UploadFile | None = File(default=None),
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
        decision_case = create_case(case_id, fields, supporting_document_name)
        create_audit_log(decision_case["id"], "CASE_CREATED", "SYSTEM", {"case_id": case_id})
        ai_analysis = save_ai_analysis(decision_case["id"], analysis, os.getenv("GEMINI_MODEL", "unknown"))
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DatabaseError as exc:
        logger.error("Decision persistence failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return AnalyzeCaseResponse(decision_case_id=decision_case["id"], ai_analysis_id=ai_analysis["id"],
        case_id=case_id, case=fields, analysis=analysis)


@app.post("/api/cases/{decision_case_id}/decision", response_model=HumanDecisionResponse)
def submit_human_decision(decision_case_id: str, request: HumanDecisionRequest) -> HumanDecisionResponse:
    try:
        return HumanDecisionResponse.model_validate(save_human_decision(decision_case_id, request))
    except DuplicateDecisionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DatabaseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/cases")
def get_cases() -> list[dict]:
    try:
        return list_cases()
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DatabaseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/cases/{decision_case_id}")
def get_case_details(decision_case_id: str) -> dict:
    try:
        return get_case(decision_case_id)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DatabaseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/dashboard/stats")
def get_dashboard_stats() -> dict[str, int]:
    try:
        return dashboard_stats()
    except DatabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DatabaseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
