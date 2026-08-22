from typing import Literal

from pydantic import BaseModel, Field


Recommendation = Literal["APPROVE", "REJECT", "NEEDS_REVIEW"]
EvidenceSource = Literal["CASE_DETAILS", "SUPPORTING_DOCUMENT"]
Severity = Literal["LOW", "MEDIUM", "HIGH"]


class EvidenceItem(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    detail: str = Field(min_length=1, max_length=1000)
    source: EvidenceSource


class RiskFlag(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    severity: Severity
    detail: str = Field(min_length=1, max_length=1000)


class AnalysisResult(BaseModel):
    recommendation: Recommendation
    confidence: int = Field(ge=0, le=100)
    summary: str = Field(min_length=1, max_length=2000)
    reasoning: str = Field(min_length=1, max_length=3000)
    evidence: list[EvidenceItem] = Field(default_factory=list, max_length=12)
    risk_flags: list[RiskFlag] = Field(default_factory=list, max_length=12)
    missing_information: list[str] = Field(default_factory=list, max_length=12)
    human_review_focus: list[str] = Field(default_factory=list, max_length=12)
    analysis_notice: str | None = Field(default=None, max_length=500)


class AnalyzeCaseResponse(BaseModel):
    decision_case_id: str
    ai_analysis_id: str
    case_id: str
    case: dict[str, str]
    analysis: AnalysisResult


FinalDecision = Literal["APPROVED", "REJECTED"]


class HumanDecisionRequest(BaseModel):
    final_decision: FinalDecision
    decision_reason: str = Field(min_length=1, max_length=3000)
    reviewer_name: str = Field(min_length=1, max_length=160)

    def model_post_init(self, __context: object) -> None:
        if not self.decision_reason.strip() or not self.reviewer_name.strip():
            raise ValueError("Decision reason and reviewer name are required.")


class HumanDecisionResponse(BaseModel):
    id: str
    decision_case_id: str
    ai_analysis_id: str
    final_decision: FinalDecision
    decision_reason: str
    reviewer_name: str
    is_override: bool
    created_at: str
