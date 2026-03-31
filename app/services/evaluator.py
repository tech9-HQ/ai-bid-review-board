"""
app/services/evaluator.py
──────────────────────────
BidReviewPipeline — the 6-stage AI governance engine.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Dict, Optional

from loguru import logger

from app.core.config import settings
from app.core.exceptions import PipelineError
from app.models.schemas import (
    AuditResult,
    BidBundle,
    EvaluationResponse,
    LegalReview,
    ReviewSession,
    StageStatus,
)
from app.services.ai_client import claude_client
from app.services.output_generator import OutputGenerator
from app.services.parser import DocumentParser
from app.services.prompts import BidPrompts


# Global session store
_session_store: dict = {}


class BidReviewPipeline:
    def __init__(self) -> None:
        self.parser = DocumentParser()
        self.output_gen = OutputGenerator()
        self.prompts = BidPrompts()

    async def run(self, deal_name: str, uploaded: dict) -> EvaluationResponse:
        # FIX: proper session_id
        session_id = str(uuid.uuid4())
        session = ReviewSession(session_id=session_id)

        start = time.perf_counter()

        try:
            # Stage 1 — Parse
            extracted = await self.parser.parse(uploaded)

            # Stage 2 — Bundle
            bundle = await self._stage_build_bundle(extracted, deal_name, session)

            # Stage 3 — Audit
            audit = await self._stage_audit(bundle, extracted, session)

            # Stage 4 — Rewrite
            revised = await self._stage_rewrite(bundle, audit, extracted, session)

            # Stage 5 — Legal
            legal = await self._stage_legal_review(extracted, session)

            # Stage 6 — Output
            output_files = await self.output_gen.generate(session)

        except Exception as exc:
            logger.exception(f"Pipeline failed: {exc}")
            raise PipelineError(str(exc))

        elapsed = time.perf_counter() - start

        # Store session
        _session_store[session_id] = session

        return EvaluationResponse(
            success=True,
            session_id=session_id,
            has_blockers=audit.scorecard.blocker_count > 0,
            recommendation=self._derive_recommendation(audit),
            bid_bundle=bundle,
            audit_result=audit,
            legal_review=legal,
            output_files=output_files,
            processing_time_seconds=round(elapsed, 2),
        )

    async def _stage_build_bundle(self, extracted, deal_name, session):
        session.update_stage("bundle", StageStatus.RUNNING)
        try:
            prompt = self.prompts.build_bundle(extracted, deal_name)

            raw = await claude_client.complete_json(
                prompt=prompt,
                system=self.prompts.BUNDLE_SYSTEM,
                model=settings.CLAUDE_FAST_MODEL,
                max_tokens=settings.AI_MAX_TOKENS,
            )

            data = json.loads(raw)
            bundle = BidBundle(**data)

            session.update_stage("bundle", StageStatus.COMPLETE)
            return bundle

        except Exception as e:
            session.update_stage("bundle", StageStatus.FAILED)
            raise PipelineError(f"Bundle failed: {e}")

    async def _stage_audit(self, bundle, extracted, session):
        session.update_stage("audit", StageStatus.RUNNING)
        try:
            prompt = self.prompts.governance_audit(bundle, extracted)

            raw = await claude_client.complete_json(
                prompt=prompt,
                system=self.prompts.AUDIT_SYSTEM,
                model=settings.CLAUDE_FAST_MODEL,
                max_tokens=settings.AI_MAX_TOKENS,
            )

            data = json.loads(raw)
            audit = AuditResult(**data)

            session.update_stage("audit", StageStatus.COMPLETE)
            return audit

        except Exception as e:
            session.update_stage("audit", StageStatus.FAILED)
            raise PipelineError(f"Audit failed: {e}")

    async def _stage_rewrite(self, bundle, audit, extracted, session):
        session.update_stage("rewrite", StageStatus.RUNNING)
        try:
            prompt = self.prompts.rewrite_proposal(bundle, audit, extracted)

            revised = await claude_client.complete(
                prompt=prompt,
                system=self.prompts.REWRITE_SYSTEM,
                model=settings.CLAUDE_FAST_MODEL,
                max_tokens=settings.AI_MAX_TOKENS,
            )

            session.update_stage("rewrite", StageStatus.COMPLETE)
            return revised

        except Exception as e:
            session.update_stage("rewrite", StageStatus.FAILED)
            raise PipelineError(f"Rewrite failed: {e}")

    async def _stage_legal_review(self, extracted, session):
        session.update_stage("legal", StageStatus.RUNNING)
        try:
            raw = await claude_client.complete_json(
                prompt=self.prompts.legal_review(
                    extracted.get("sow", ""),
                    extracted.get("tnc", ""),
                    extracted.get("commercial", ""),
                ),
                system=self.prompts.LEGAL_SYSTEM,
                model=settings.CLAUDE_LEGAL_MODEL,
                max_tokens=settings.AI_MAX_TOKENS,
            )

            data = json.loads(raw)
            legal = LegalReview(**data)

            session.update_stage("legal", StageStatus.COMPLETE)
            return legal

        except Exception as e:
            session.update_stage("legal", StageStatus.FAILED)
            raise PipelineError(f"Legal failed: {e}")

    def _derive_recommendation(self, audit: AuditResult) -> str:
        score = audit.scorecard.overall_score
        blockers = audit.scorecard.blocker_count

        if blockers > 0:
            return "No Go"
        if score >= 85:
            return "Go"
        if score >= 65:
            return "Conditional Go"
        return "No Go"