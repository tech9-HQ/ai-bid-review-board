"""
app/services/evaluator.py
──────────────────────────
Orchestrates the full 6-stage Bid Review Board pipeline.

Stage 1 — Document Extract
Stage 2 — Bid Bundle Build        (OpenAI)
Stage 3 — Governance Audit        (OpenAI)
Stage 4 — Proposal Rewrite        (OpenAI)
Stage 5 — Legal Review            (Claude)
Stage 6 — Publish Outputs         (local generation)

Each stage is atomic — failure raises a BidReviewError with full context.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from loguru import logger

from app.core.config import settings
from app.core.exceptions import AIResponseParseError, OutputGenerationError
from app.models.schemas import (
    AuditResult,
    BidBundle,
    GovernanceScorecard,
    AuditArea,
    Issue,
    IssueCategory,
    IssueStatus,
    LegalReview,
    ProposalRewrite,
    ReviewSession,
    ReviewStage,
    StageStatus,
    Severity,
    Verdict,
    Recommendation,
)
from app.services.ai_client import AnthropicClient, OpenAIClient
from app.services.output_generator import generate_all_outputs
from app.services.parser import extract_text_from_bytes, truncate_text
from app.services.prompts import (
    BID_BUNDLE_SYSTEM,
    AUDIT_SYSTEM,
    REWRITE_SYSTEM,
    LEGAL_SYSTEM,
    build_bid_bundle_prompt,
    build_audit_prompt,
    build_rewrite_prompt,
    build_legal_prompt,
)



# ── In-Memory Session Store ───────────────────────────────────────────────────
# Holds ReviewSession objects between /evaluate/ and /generate-docs/ calls.
# For production at scale, replace with Redis or a database.
_session_store: dict[str, "ReviewSession"] = {}


class BidReviewPipeline:
    """
    Stateless pipeline executor.

    Usage:
        pipeline = BidReviewPipeline()
        session = await pipeline.run(deal_name, uploaded_files)
    """

    def __init__(self) -> None:
        self._openai = OpenAIClient()
        self._claude = AnthropicClient()

    async def run(
        self,
        deal_name: str,
        uploaded_files: dict[str, tuple[bytes, str]],
        # key = document role (e.g. "crm", "proposal", "sow")
        # value = (file_bytes, filename)
    ) -> ReviewSession:
        """
        Execute the full pipeline and return a completed ReviewSession.

        Args:
            deal_name: Human-readable deal / customer name.
            uploaded_files: Dict of {role: (bytes, filename)} from the API layer.

        Returns:
            ReviewSession with all stages completed (or failed).
        """
        session = ReviewSession(
            session_id=str(uuid.uuid4()),
            deal_name=deal_name,
        )

        logger.info(f"[Pipeline] Starting review | session={session.session_id} | deal={deal_name}")

        # ── Stage 1: Document Extract ──────────────────────────────────────────
        self._set_stage(session, 0, StageStatus.RUNNING)
        try:
            session.documents = self._stage1_extract(uploaded_files)
            self._set_stage(session, 0, StageStatus.DONE)
            logger.info(f"[Stage 1] Extracted {len(session.documents)} documents")
        except Exception as exc:
            self._set_stage(session, 0, StageStatus.FAILED, str(exc))
            raise

        # ── Stage 2: Bid Bundle Build ──────────────────────────────────────────
        self._set_stage(session, 1, StageStatus.RUNNING)
        try:
            session.bid_bundle = self._stage2_bid_bundle(session.documents)
            self._set_stage(session, 1, StageStatus.DONE)
            logger.info("[Stage 2] Bid bundle built successfully")
        except Exception as exc:
            self._set_stage(session, 1, StageStatus.FAILED, str(exc))
            raise

        # ── Stage 3: Governance Audit ──────────────────────────────────────────
        self._set_stage(session, 2, StageStatus.RUNNING)
        try:
            session.audit_result = self._stage3_audit(session.bid_bundle, session.documents)
            self._set_stage(session, 2, StageStatus.DONE)
            logger.info(
                f"[Stage 3] Audit complete | "
                f"score={session.audit_result.scorecard.overall_score} | "
                f"blockers={session.audit_result.scorecard.blocker_count}"
            )
        except Exception as exc:
            self._set_stage(session, 2, StageStatus.FAILED, str(exc))
            raise

        # ── Stage 4: Proposal Rewrite ──────────────────────────────────────────
        self._set_stage(session, 3, StageStatus.RUNNING)
        try:
            session.proposal_rewrite = self._stage4_rewrite(
                session.bid_bundle,
                session.audit_result.issues,
                session.documents.get("proposal", ""),
            )
            self._set_stage(session, 3, StageStatus.DONE)
            logger.info("[Stage 4] Proposal rewrite complete")
        except Exception as exc:
            self._set_stage(session, 3, StageStatus.FAILED, str(exc))
            raise

        # ── Stage 5: Legal Review ──────────────────────────────────────────────
        if not self._claude.is_available():
            self._set_stage(session, 4, StageStatus.SKIPPED, "ANTHROPIC_API_KEY not set")
            logger.warning("[Stage 5] Skipped — no Anthropic API key configured. Add ANTHROPIC_API_KEY to .env to enable legal review.")
        else:
            self._set_stage(session, 4, StageStatus.RUNNING)
            try:
                session.legal_review = self._stage5_legal(session.bid_bundle, session.documents)
                self._set_stage(session, 4, StageStatus.DONE)
                logger.info("[Stage 5] Legal review complete")
            except Exception as exc:
                self._set_stage(session, 4, StageStatus.FAILED, str(exc))
                raise

        # Stage 6 (Publish Outputs) is NOT run automatically.
        # The caller must explicitly call generate_documents(session_id) after
        # reviewing results on screen.
        self._set_stage(session, 5, StageStatus.PENDING)

        # Persist session in memory so generate_documents() can retrieve it later
        _session_store[session.session_id] = session

        logger.info(f"[Pipeline] ✓ Review complete | session={session.session_id} | awaiting doc generation request")
        return session

    def generate_documents(self, session_id: str) -> ReviewSession:
        """
        Stage 6: Generate DOCX/XLSX output files for a previously reviewed session.

        Called explicitly by POST /sessions/{session_id}/generate-docs/
        after the user has reviewed results on screen.

        Args:
            session_id: ID returned by run_review().

        Returns:
            Updated ReviewSession with output_files populated.

        Raises:
            KeyError: If session_id not found in store.
            OutputGenerationError: If document generation fails.
        """
        session = _session_store.get(session_id)
        if session is None:
            from app.core.exceptions import BidReviewError
            raise BidReviewError(
                f"Session '{session_id}' not found.",
                detail="Session may have expired or never existed. Re-submit the deal to create a new session.",
            )

        if session.output_files:
            logger.info(f"[Stage 6] Documents already generated for session={session_id}")
            return session

        self._set_stage(session, 5, StageStatus.RUNNING)
        try:
            session.output_files = generate_all_outputs(session)
            self._set_stage(session, 5, StageStatus.DONE)
            logger.info(f"[Stage 6] Generated {len(session.output_files)} output files for session={session_id}")
        except Exception as exc:
            self._set_stage(session, 5, StageStatus.FAILED, str(exc))
            raise

        return session

    # ── Stage Implementations ──────────────────────────────────────────────────

    def _stage1_extract(
        self, uploaded_files: dict[str, tuple[bytes, str]]
    ) -> dict[str, str]:
        """Extract text from all uploaded documents."""
        documents: dict[str, str] = {}
        for role, (file_bytes, filename) in uploaded_files.items():
            text = extract_text_from_bytes(file_bytes, filename)
            documents[role] = truncate_text(text, max_chars=10000)
            logger.debug(f"[Stage 1] {role} → {len(documents[role])} chars")
        return documents

    def _stage2_bid_bundle(self, documents: dict[str, str]) -> BidBundle:
        """Build structured BidBundle from document text via OpenAI."""
        prompt = build_bid_bundle_prompt(documents)
        raw = self._openai.chat(
            system=BID_BUNDLE_SYSTEM,
            user=prompt,
            model=settings.OPENAI_AUDIT_MODEL,
            context="stage2_bid_bundle",
        )
        return BidBundle.model_validate(raw)

    def _stage3_audit(
        self, bid_bundle: BidBundle, documents: dict[str, str]
    ) -> AuditResult:
        """Run full governance audit via OpenAI."""
        prompt = build_audit_prompt(bid_bundle, documents)
        raw = self._openai.chat(
            system=AUDIT_SYSTEM,
            user=prompt,
            model=settings.OPENAI_AUDIT_MODEL,
            context="stage3_audit",
        )

        try:
            # Parse scorecard
            scorecard_data = raw.get("scorecard", {})
            areas = [
                AuditArea(
                    area=a.get("area", ""),
                    verdict=Verdict(a.get("verdict", "PENDING")),
                    score=int(a.get("score", 0)),
                    issue_count=int(a.get("issue_count", 0)),
                    notes=a.get("notes", ""),
                )
                for a in scorecard_data.get("areas", [])
            ]
            scorecard = GovernanceScorecard(
                areas=areas,
                overall_score=int(scorecard_data.get("overall_score", 0)),
                blocker_count=int(scorecard_data.get("blocker_count", 0)),
                recommendation=Recommendation(
                    scorecard_data.get("recommendation", "Conditional Go")
                ),
                clarifying_questions=scorecard_data.get("clarifying_questions", []),
            )

            # Parse issues
            issues = [
                Issue(
                    id=i.get("id", f"ISS-{idx:03d}"),
                    category=self._safe_category(i.get("category", "Scope")),
                    severity=Severity(i.get("severity", "MEDIUM")),
                    finding=i.get("finding", ""),
                    evidence=i.get("evidence", ""),
                    impact=i.get("impact", ""),
                    fix=i.get("fix", ""),
                    owner=i.get("owner", "Presales"),
                    status=IssueStatus(i.get("status", "Open")),
                )
                for idx, i in enumerate(raw.get("issues", []))
            ]

            return AuditResult(
                scorecard=scorecard,
                issues=issues,
                raw_response=str(raw),
            )

        except Exception as exc:
            raise AIResponseParseError(
                "Failed to parse Stage 3 audit response.",
                detail=str(exc),
            ) from exc

    def _stage4_rewrite(
        self,
        bid_bundle: BidBundle,
        issues: list[Issue],
        original_proposal: str,
    ) -> ProposalRewrite:
        """Rewrite proposal sections to fix all issues via OpenAI."""
        prompt = build_rewrite_prompt(bid_bundle, issues, original_proposal)
        raw = self._openai.chat(
            system=REWRITE_SYSTEM,
            user=prompt,
            model=settings.OPENAI_REWRITE_MODEL,
            context="stage4_rewrite",
        )
        return ProposalRewrite(
            executive_summary=raw.get("executive_summary", ""),
            solution_approach=raw.get("solution_approach", ""),
            architecture_justification=raw.get("architecture_justification", ""),
            sizing_assumptions=raw.get("sizing_assumptions", ""),
            scope_and_deliverables=raw.get("scope_and_deliverables", ""),
            milestones_and_acceptance=raw.get("milestones_and_acceptance", ""),
            dependencies=raw.get("dependencies", ""),
            commercial_clarifications=raw.get("commercial_clarifications", ""),
            assumptions_and_exclusions=raw.get("assumptions_and_exclusions", ""),
            raw_response=str(raw),
        )

    def _stage5_legal(
        self, bid_bundle: BidBundle, documents: dict[str, str]
    ) -> LegalReview:
        """Legal clause review and rewrite via Claude."""
        prompt = build_legal_prompt(bid_bundle, documents)
        raw = self._claude.chat(
            system=LEGAL_SYSTEM,
            user=prompt,
            model=settings.CLAUDE_LEGAL_MODEL,
            context="stage5_legal",
        )
        return LegalReview(
            revised_sla_clause=raw.get("revised_sla_clause", ""),
            revised_liability_clause=raw.get("revised_liability_clause", ""),
            revised_change_control=raw.get("revised_change_control", ""),
            revised_acceptance_criteria=raw.get("revised_acceptance_criteria", ""),
            revised_warranty_clause=raw.get("revised_warranty_clause", ""),
            additional_recommendations=raw.get("additional_recommendations", []),
            raw_response=str(raw),
        )

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _set_stage(
        session: ReviewSession,
        index: int,
        status: StageStatus,
        error: str | None = None,
    ) -> None:
        session.stages[index].status = status
        session.stages[index].error = error

    @staticmethod
    def _safe_category(raw: str) -> IssueCategory:
        mapping = {
            "sizing": IssueCategory.SIZING,
            "architecture": IssueCategory.ARCHITECTURE,
            "boq": IssueCategory.BOQ,
            "legal": IssueCategory.LEGAL,
            "commercial": IssueCategory.COMMERCIAL,
            "scope": IssueCategory.SCOPE,
            "delivery": IssueCategory.DELIVERY,
            "business fit": IssueCategory.BUSINESS_FIT,
            "requirements": IssueCategory.REQUIREMENTS,
            "operability": IssueCategory.OPERABILITY,
        }
        return mapping.get(raw.lower(), IssueCategory.SCOPE)