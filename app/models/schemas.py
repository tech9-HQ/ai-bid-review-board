"""
app/models/schemas.py
─────────────────────
All Pydantic v2 request/response models for the bid review pipeline.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ── Enums ─────────────────────────────────────────────────────────────────


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    SKIPPED = "skipped"
    FAILED = "failed"


class Severity(str, Enum):
    BLOCKER = "BLOCKER"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class AreaStatus(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


# ── Input Models ──────────────────────────────────────────────────────────


class DocumentSet(BaseModel):
    """In-memory representation of uploaded files after validation."""
    deal_name: str
    crm: bytes
    crm_filename: str
    requirements: bytes
    requirements_filename: str
    sizing: bytes
    sizing_filename: str
    boq: bytes
    boq_filename: str
    proposal: bytes
    proposal_filename: str
    # Optional documents
    commercial: Optional[bytes] = None
    commercial_filename: Optional[str] = None
    sow: Optional[bytes] = None
    sow_filename: Optional[str] = None
    tnc: Optional[bytes] = None
    tnc_filename: Optional[str] = None


# ── Pipeline Stage Tracking ───────────────────────────────────────────────


class ReviewSession(BaseModel):
    """Tracks stage statuses for a single pipeline run."""
    session_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    stages: Dict[str, StageStatus] = Field(
        default_factory=lambda: {
            "extract": StageStatus.PENDING,
            "bundle": StageStatus.PENDING,
            "audit": StageStatus.PENDING,
            "rewrite": StageStatus.PENDING,
            "legal": StageStatus.PENDING,
            "publish": StageStatus.PENDING,
        }
    )

    def update_stage(self, stage: str, status: StageStatus) -> None:
        self.stages[stage] = status


# ── AI Output Models ──────────────────────────────────────────────────────


class RequirementsCoverage(BaseModel):
    covered: List[str] = Field(default_factory=list)
    gaps: List[str] = Field(default_factory=list)


class BidBundle(BaseModel):
    """Structured extraction of the deal (Stage 2 output)."""
    deal_name: str
    customer: str
    solution_summary: str
    architecture_components: List[str] = Field(default_factory=list)
    total_value_usd: Optional[float] = None
    delivery_timeline_weeks: Optional[int] = None
    key_risks: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    exclusions: List[str] = Field(default_factory=list)
    requirements_coverage: RequirementsCoverage = Field(
        default_factory=RequirementsCoverage
    )


class GovernanceArea(BaseModel):
    """Score for one of the 10 governance areas."""
    id: str
    name: str
    score: int = Field(ge=0, le=10)
    status: AreaStatus

    @field_validator("score")
    @classmethod
    def clamp_score(cls, v: int) -> int:
        return max(0, min(10, v))


class Scorecard(BaseModel):
    overall_score: int = Field(ge=0, le=100)
    blocker_count: int = Field(ge=0)
    major_count: int = Field(ge=0)
    minor_count: int = Field(ge=0)
    areas: List[GovernanceArea] = Field(default_factory=list)


class Issue(BaseModel):
    """A single governance finding (Stage 3 output)."""
    id: str
    area: str
    severity: Severity
    finding: str
    fix: str
    reference_doc: str = ""


class AuditResult(BaseModel):
    """Full governance audit output (Stage 3 output)."""
    scorecard: Scorecard
    issues: List[Issue] = Field(default_factory=list)
    executive_summary: str = ""


class LegalClause(BaseModel):
    clause_ref: str
    document: str
    risk_type: str
    risk_level: RiskLevel
    description: str
    recommendation: str


class RecommendedChange(BaseModel):
    clause_ref: str
    current_text_summary: str
    proposed_change: str
    rationale: str


class LegalReview(BaseModel):
    """Legal clause analysis output (Stage 5 output)."""
    summary: str
    risk_level: RiskLevel = RiskLevel.UNKNOWN
    clauses: List[LegalClause] = Field(default_factory=list)
    recommended_changes: List[RecommendedChange] = Field(default_factory=list)
    show_stoppers: List[str] = Field(default_factory=list)


# ── API Response Models ───────────────────────────────────────────────────


class EvaluationResponse(BaseModel):
    """Full pipeline response returned to the API caller."""
    success: bool
    session_id: str
    has_blockers: bool
    recommendation: str
    bid_bundle: BidBundle
    audit_result: AuditResult
    legal_review: Optional[LegalReview] = None
    output_files: Dict[str, str] = Field(default_factory=dict)
    processing_time_seconds: float = 0.0


class SessionSummary(BaseModel):
    """Lightweight session record for the /sessions/ listing."""
    session_id: str
    deal_name: str
    recommendation: str
    overall_score: int
    blocker_count: int
    created_at: datetime
    output_files: Dict[str, str]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "error"]
    version: str
    environment: str
    ai_provider: str = "Anthropic Claude"
    fast_model: str
    legal_model: str

class Verdict(str, Enum):
    APPROVE = "approve"
    REVIEW = "review"
    REJECT = "reject"