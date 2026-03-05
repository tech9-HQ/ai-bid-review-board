"""
app/models/schemas.py
──────────────────────
All Pydantic v2 schemas used across the API.

Organised into:
  - BidBundle       → structured deal intelligence object
  - IssueLog        → per-finding record
  - GovernanceScore → per-area verdict
  - AuditResult     → full Stage 3 ChatGPT output
  - RewriteResult   → Stage 4 ChatGPT output
  - LegalResult     → Stage 5 Claude output
  - ReviewSession   → complete deal review state
  - API responses
"""
from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


# ── Enums ─────────────────────────────────────────────────────────────────────

class Verdict(str, Enum):
    PASS = "PASS"
    REVIEW = "REVIEW"
    BLOCKER = "BLOCKER"
    PENDING = "PENDING"


class Severity(str, Enum):
    BLOCKER = "BLOCKER"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class Recommendation(str, Enum):
    GO = "Go"
    CONDITIONAL_GO = "Conditional Go"
    NO_GO = "No Go"


class IssueStatus(str, Enum):
    OPEN = "Open"
    IN_PROGRESS = "In Progress"
    RESOLVED = "Resolved"


class IssueCategory(str, Enum):
    BUSINESS_FIT = "Business Fit"
    REQUIREMENTS = "Requirements"
    ARCHITECTURE = "Architecture"
    SIZING = "Sizing"
    BOQ = "BOQ"
    SCOPE = "Scope"
    DELIVERY = "Delivery"
    COMMERCIAL = "Commercial"
    LEGAL = "Legal"
    OPERABILITY = "Operability"


# ── Bid Bundle ────────────────────────────────────────────────────────────────

class DealInfo(BaseModel):
    customer: str = ""
    industry: str = ""
    locations: list[str] = []
    business_objective: str = ""
    pain_points: list[str] = []
    success_criteria: list[str] = []
    timeline: str = ""
    budget_signals: str = ""


class RequirementsInfo(BaseModel):
    must_have: list[str] = []
    should_have: list[str] = []
    constraints: list[str] = []
    compliance: list[str] = []


class SolutionInfo(BaseModel):
    architecture_type: str = ""
    technologies: list[str] = []
    dependencies: list[str] = []
    assumptions: list[str] = []
    exclusions: list[str] = []


class SizingInfo(BaseModel):
    workload_type: str = ""
    vm_count: int = 0
    cpu_ratio: str = ""
    memory_gb: float = 0
    storage_usable_tb: float = 0
    iops: int = 0
    growth_pct: float = 0
    ha_model: str = ""


class BOQInfo(BaseModel):
    hardware: list[str] = []
    software: list[str] = []
    licenses: list[str] = []
    support: list[str] = []
    services: list[str] = []


class CommercialInfo(BaseModel):
    deal_value: str = ""
    discount_pct: float = 0
    margin_pct: float = 0
    payment_terms: str = ""
    validity_days: int = 0


class SOWInfo(BaseModel):
    deliverables: list[str] = []
    milestones: list[str] = []
    acceptance_criteria: list[str] = []
    customer_responsibilities: list[str] = []


class TnCInfo(BaseModel):
    liability_cap: str = ""
    warranty: str = ""
    sla_summary: str = ""
    penalties: str = ""
    change_control: str = ""


class BidBundle(BaseModel):
    """Master deal intelligence object — every stage reads from this."""
    deal: DealInfo = Field(default_factory=DealInfo)
    requirements: RequirementsInfo = Field(default_factory=RequirementsInfo)
    solution: SolutionInfo = Field(default_factory=SolutionInfo)
    sizing: SizingInfo = Field(default_factory=SizingInfo)
    boq: BOQInfo = Field(default_factory=BOQInfo)
    commercials: CommercialInfo = Field(default_factory=CommercialInfo)
    sow: SOWInfo = Field(default_factory=SOWInfo)
    tnc: TnCInfo = Field(default_factory=TnCInfo)


# ── Issue Log ─────────────────────────────────────────────────────────────────

class Issue(BaseModel):
    id: str                           # e.g. INF-SIZ-004
    category: IssueCategory
    severity: Severity
    finding: str
    evidence: str
    impact: str
    fix: str
    owner: str = "Presales"
    status: IssueStatus = IssueStatus.OPEN


# ── Governance Score ──────────────────────────────────────────────────────────

class AuditArea(BaseModel):
    area: str
    verdict: Verdict
    score: int = Field(ge=0, le=100)
    issue_count: int = 0
    notes: str = ""


AUDIT_AREAS = [
    "Business Fit",
    "Requirements Traceability",
    "Architecture Integrity",
    "Sizing Validity",
    "BOQ Consistency",
    "Scope Completeness",
    "Delivery Risk",
    "Commercial Safety",
    "Legal Risk",
    "Operability",
]


class GovernanceScorecard(BaseModel):
    areas: list[AuditArea] = []
    overall_score: int = Field(default=0, ge=0, le=100)
    blocker_count: int = 0
    recommendation: Recommendation = Recommendation.CONDITIONAL_GO
    clarifying_questions: list[str] = []


# ── Stage Outputs ─────────────────────────────────────────────────────────────

class AuditResult(BaseModel):
    """Stage 3: ChatGPT Governance Audit output."""
    scorecard: GovernanceScorecard
    issues: list[Issue] = []
    raw_response: str = ""


class ProposalRewrite(BaseModel):
    """Stage 4: ChatGPT Proposal Rewrite output."""
    executive_summary: str = ""
    solution_approach: str = ""
    architecture_justification: str = ""
    sizing_assumptions: str = ""
    scope_and_deliverables: str = ""
    milestones_and_acceptance: str = ""
    dependencies: str = ""
    commercial_clarifications: str = ""
    assumptions_and_exclusions: str = ""
    raw_response: str = ""


class LegalReview(BaseModel):
    """Stage 5: Claude Legal Review output."""
    revised_sla_clause: str = ""
    revised_liability_clause: str = ""
    revised_change_control: str = ""
    revised_acceptance_criteria: str = ""
    revised_warranty_clause: str = ""
    additional_recommendations: list[str] = []
    raw_response: str = ""


# ── Review Session ────────────────────────────────────────────────────────────

class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"  # Stage intentionally bypassed (e.g. missing API key)


class ReviewStage(BaseModel):
    name: str
    status: StageStatus = StageStatus.PENDING
    error: str | None = None


class ReviewSession(BaseModel):
    """Complete state of a deal going through the board."""
    session_id: str
    deal_name: str

    # Document texts (populated in Stage 1)
    documents: dict[str, str] = {}

    # Stage 2 output
    bid_bundle: BidBundle | None = None

    # Stage 3 output
    audit_result: AuditResult | None = None

    # Stage 4 output
    proposal_rewrite: ProposalRewrite | None = None

    # Stage 5 output
    legal_review: LegalReview | None = None

    # Output file paths
    output_files: dict[str, str] = {}

    # Pipeline state
    stages: list[ReviewStage] = Field(
        default_factory=lambda: [
            ReviewStage(name="Document Extract"),
            ReviewStage(name="Bid Bundle Build"),
            ReviewStage(name="Governance Audit"),
            ReviewStage(name="Proposal Rewrite"),
            ReviewStage(name="Legal Review"),
            ReviewStage(name="Publish Outputs"),
        ]
    )

    @property
    def current_stage_index(self) -> int:
        for i, s in enumerate(self.stages):
            if s.status in (StageStatus.PENDING, StageStatus.RUNNING):
                return i
        return len(self.stages)

    @property
    def is_complete(self) -> bool:
        return all(s.status in (StageStatus.DONE, StageStatus.SKIPPED) for s in self.stages)

    @property
    def has_blockers(self) -> bool:
        if self.audit_result is None:
            return False
        return any(
            i.severity == Severity.BLOCKER
            for i in self.audit_result.issues
        )


# ── API Response Envelopes ────────────────────────────────────────────────────

class SuccessResponse(BaseModel):
    success: bool = True
    data: Any = None


class EvaluateResponse(BaseModel):
    """
    Returned by POST /evaluate/
    Contains all review results for on-screen display.
    Does NOT include generated documents — those are triggered separately.
    """
    success: bool = True
    session_id: str
    deal_name: str
    bid_bundle: BidBundle
    audit_result: AuditResult
    proposal_rewrite: ProposalRewrite
    legal_review: LegalReview | None = None
    has_blockers: bool
    recommendation: Recommendation
    stages: list[ReviewStage] = []


class GenerateDocsResponse(BaseModel):
    """
    Returned by POST /sessions/{session_id}/generate-docs/
    Contains download URLs for all generated documents.
    """
    success: bool = True
    session_id: str
    output_files: dict[str, str]   # role -> download URL