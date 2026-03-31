"""
tests/test_evaluator.py
────────────────────────
Test suite for the Claude-only bid review pipeline.

Run with:
  pytest tests/ -v
  pytest tests/ -v --cov=app --cov-report=term-missing
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.models.schemas import (
    AuditResult,
    BidBundle,
    DocumentSet,
    EvaluationResponse,
    GovernanceArea,
    Issue,
    LegalReview,
    RequirementsCoverage,
    Scorecard,
    Severity,
    StageStatus,
)
from app.services.evaluator import BidReviewPipeline
from app.services.prompts import BidPrompts
from main import app


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def sample_document_set() -> DocumentSet:
    return DocumentSet(
        deal_name="Test Deal — ACME Corp",
        crm=b"CRM: Pain points include legacy infra, slow DR recovery.",
        crm_filename="crm.txt",
        requirements=b"REQ-001: HA architecture. REQ-002: < 4h RTO. REQ-003: 3-year support.",
        requirements_filename="requirements.txt",
        sizing=b"CPU: 2:1 ratio. Memory: 256GB. Storage: 50TB.",
        sizing_filename="sizing.txt",
        boq=b"Item 1: 4x Servers. Item 2: SW Licenses. Item 3: Support.",
        boq_filename="boq.txt",
        proposal=b"Proposal: We propose a hyper-converged solution for ACME Corp.",
        proposal_filename="proposal.txt",
        sow=b"SOW: Delivery in 12 weeks. Liability capped at 1x contract value.",
        sow_filename="sow.txt",
    )


@pytest.fixture
def sample_bid_bundle() -> BidBundle:
    return BidBundle(
        deal_name="Test Deal",
        customer="ACME Corp",
        solution_summary="HCI solution to replace legacy infrastructure.",
        architecture_components=["HCI Nodes", "Networking", "SW Licenses"],
        total_value_usd=250000,
        delivery_timeline_weeks=12,
        key_risks=["Lead time risk on hardware"],
        assumptions=["Customer provides rack space"],
        exclusions=["Migration services"],
        requirements_coverage=RequirementsCoverage(
            covered=["REQ-001", "REQ-002"],
            gaps=["REQ-003"],
        ),
    )


@pytest.fixture
def sample_audit_result() -> AuditResult:
    return AuditResult(
        scorecard=Scorecard(
            overall_score=72,
            blocker_count=1,
            major_count=2,
            minor_count=3,
            areas=[
                GovernanceArea(id="GOV-01", name="Business Fit", score=8, status="pass"),
                GovernanceArea(id="GOV-09", name="Legal Risk", score=5, status="warn"),
            ],
        ),
        issues=[
            Issue(
                id="INF-SIZ-004",
                area="Sizing Validity",
                severity=Severity.BLOCKER,
                finding="DR node count insufficient for failover",
                fix="Increase DR node count from 2 to 4",
                reference_doc="sizing.txt",
            ),
        ],
        executive_summary="The proposal has 1 blocker that must be resolved before submission.",
    )


@pytest.fixture
def sample_legal_review() -> LegalReview:
    return LegalReview(
        summary="Moderate risk. Liability cap needs review.",
        risk_level="medium",
        clauses=[],
        recommended_changes=[],
        show_stoppers=[],
    )


# ── Unit Tests: BidPrompts ─────────────────────────────────────────────────


class TestBidPrompts:
    def test_build_bundle_includes_deal_name(self):
        prompts = BidPrompts()
        extracted = {"crm": "CRM text here", "requirements": "REQ text here"}
        result = prompts.build_bundle(extracted, "My Deal")
        assert "My Deal" in result
        assert "<crm>" in result
        assert "<requirements>" in result

    def test_format_documents_truncates_long_content(self):
        prompts = BidPrompts()
        long_text = "x" * 20000
        result = prompts._format_documents({"proposal": long_text})
        assert "truncated" in result
        assert len(result) < len(long_text)

    def test_legal_review_skips_empty_docs(self):
        prompts = BidPrompts()
        result = prompts.legal_review("SOW content", "", "")
        assert "<sow>" in result
        assert "<terms_and_conditions>" not in result

    def test_governance_audit_includes_all_areas(self):
        prompts = BidPrompts()
        bundle = MagicMock()
        bundle.model_dump_json.return_value = '{"deal_name": "test"}'
        result = prompts.governance_audit(bundle, {"proposal": "content"})
        assert "Business Fit" in result
        assert "Legal Risk" in result
        assert "BOQ Consistency" in result


# ── Unit Tests: Pipeline Stages ────────────────────────────────────────────


class TestBidReviewPipeline:
    @pytest.mark.asyncio
    async def test_stage_extract_returns_dict(self, sample_document_set):
        """Stage 1 should return a dict of doc_type -> text."""
        pipeline = BidReviewPipeline()
        with patch.object(
            pipeline.parser, "extract_all", new_callable=AsyncMock
        ) as mock_extract:
            mock_extract.return_value = {
                "crm": "crm text",
                "proposal": "proposal text",
            }
            from app.models.schemas import ReviewSession
            session = ReviewSession(session_id="test-123")
            result = await pipeline._stage_extract(sample_document_set, session)

        assert isinstance(result, dict)
        assert "crm" in result

    @pytest.mark.asyncio
    async def test_stage_bundle_parses_json(self, sample_document_set, sample_bid_bundle):
        """Stage 2 should call Claude and parse JSON into BidBundle."""
        pipeline = BidReviewPipeline()
        extracted = {"crm": "crm text", "proposal": "proposal text"}

        with patch(
            "app.services.evaluator.claude_client.complete_json",
            new_callable=AsyncMock,
        ) as mock_claude:
            mock_claude.return_value = sample_bid_bundle.model_dump_json()
            from app.models.schemas import ReviewSession
            session = ReviewSession(session_id="test-123")
            result = await pipeline._stage_build_bundle(extracted, "Test Deal", session)

        assert isinstance(result, BidBundle)
        assert result.customer == "ACME Corp"

    @pytest.mark.asyncio
    async def test_stage_audit_returns_audit_result(
        self, sample_bid_bundle, sample_audit_result
    ):
        """Stage 3 should call Claude and parse JSON into AuditResult."""
        pipeline = BidReviewPipeline()
        extracted = {"proposal": "proposal text"}

        with patch(
            "app.services.evaluator.claude_client.complete_json",
            new_callable=AsyncMock,
        ) as mock_claude:
            mock_claude.return_value = sample_audit_result.model_dump_json()
            from app.models.schemas import ReviewSession
            session = ReviewSession(session_id="test-123")
            result = await pipeline._stage_audit(sample_bid_bundle, extracted, session)

        assert isinstance(result, AuditResult)
        assert result.scorecard.blocker_count == 1

    @pytest.mark.asyncio
    async def test_stage_legal_skipped_when_no_docs(self):
        """Stage 5 should skip gracefully when no legal docs are provided."""
        pipeline = BidReviewPipeline()
        extracted = {"crm": "crm text", "proposal": "proposal text"}

        from app.models.schemas import ReviewSession
        session = ReviewSession(session_id="test-123")
        result = await pipeline._stage_legal_review(extracted, session)

        assert result.risk_level == "unknown"
        assert session.stages["legal"] == StageStatus.SKIPPED

    def test_derive_recommendation_go(self, sample_audit_result):
        sample_audit_result.scorecard.blocker_count = 0
        sample_audit_result.scorecard.overall_score = 90
        rec = BidReviewPipeline._derive_recommendation(sample_audit_result)
        assert rec == "Go"

    def test_derive_recommendation_no_go_blocker(self, sample_audit_result):
        rec = BidReviewPipeline._derive_recommendation(sample_audit_result)
        assert "No Go" in rec
        assert "blocker" in rec

    def test_derive_recommendation_conditional(self, sample_audit_result):
        sample_audit_result.scorecard.blocker_count = 0
        sample_audit_result.scorecard.overall_score = 70
        rec = BidReviewPipeline._derive_recommendation(sample_audit_result)
        assert rec == "Conditional Go"


# ── Integration Tests: API Endpoints ──────────────────────────────────────


class TestAPIEndpoints:
    def test_health_check(self):
        with TestClient(app) as client:
            response = client.get("/health/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["ai_provider"] == "Anthropic Claude"
        assert "claude" in data["fast_model"].lower()

    def test_list_sessions_empty(self):
        with TestClient(app) as client:
            response = client.get("/sessions/")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_get_nonexistent_session(self):
        with TestClient(app) as client:
            response = client.get("/sessions/nonexistent-id")
        assert response.status_code == 404

    def test_download_nonexistent_file(self):
        with TestClient(app) as client:
            response = client.get("/outputs/fake-session/fake-file.docx")
        assert response.status_code == 404