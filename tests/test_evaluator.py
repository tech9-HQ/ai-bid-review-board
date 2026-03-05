"""
tests/test_evaluator.py
────────────────────────
Unit tests for the Bid Review Board pipeline.

Run with:
    pytest tests/ -v
    pytest tests/ -v --cov=app --cov-report=term-missing
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.models.schemas import (
    BidBundle,
    DealInfo,
    AuditResult,
    GovernanceScorecard,
    AuditArea,
    Issue,
    IssueCategory,
    Severity,
    Verdict,
    Recommendation,
    IssueStatus,
    ProposalRewrite,
    LegalReview,
)
from app.services.parser import extract_text_from_bytes, truncate_text
from app.services.prompts import (
    build_bid_bundle_prompt,
    build_audit_prompt,
    build_rewrite_prompt,
    build_legal_prompt,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_bundle() -> BidBundle:
    return BidBundle(
        deal=DealInfo(
            customer="Test Bank",
            industry="Banking",
            business_objective="Modernise core banking infrastructure",
            pain_points=["Legacy hardware", "Downtime risk"],
        )
    )


@pytest.fixture
def sample_issue() -> Issue:
    return Issue(
        id="INF-SIZ-001",
        category=IssueCategory.SIZING,
        severity=Severity.BLOCKER,
        finding="DR node count insufficient",
        evidence="Sizing sheet shows 1 spare node, HA requires N+1",
        impact="Failover will cause outage",
        fix="Increase node count to 4",
        owner="Presales",
        status=IssueStatus.OPEN,
    )


@pytest.fixture
def sample_audit(sample_issue) -> AuditResult:
    return AuditResult(
        scorecard=GovernanceScorecard(
            areas=[
                AuditArea(area="Business Fit", verdict=Verdict.PASS, score=90),
                AuditArea(area="Sizing Validity", verdict=Verdict.BLOCKER, score=40, issue_count=1),
            ],
            overall_score=65,
            blocker_count=1,
            recommendation=Recommendation.CONDITIONAL_GO,
        ),
        issues=[sample_issue],
    )


# ── Parser Tests ──────────────────────────────────────────────────────────────

class TestParser:
    def test_truncate_short_text(self):
        text = "Hello world"
        result = truncate_text(text, max_chars=100)
        assert result == text

    def test_truncate_long_text(self):
        text = "A" * 10000
        result = truncate_text(text, max_chars=1000)
        assert len(result) < 2000
        assert "TRUNCATED" in result

    def test_extract_txt_bytes(self):
        content = b"This is a test document.\nLine 2."
        result = extract_text_from_bytes(content, "test.txt")
        assert "test document" in result

    def test_unsupported_extension(self):
        from app.core.exceptions import UnsupportedFileTypeError
        with pytest.raises(UnsupportedFileTypeError):
            extract_text_from_bytes(b"data", "file.psd")

    def test_extract_pdf_bytes(self):
        """Test PDF extraction with a minimal in-memory PDF."""
        # Minimal valid PDF bytes
        minimal_pdf = (
            b"%PDF-1.4\n"
            b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
            b"xref\n0 4\n0000000000 65535 f\n"
            b"0000000009 00000 n\n0000000058 00000 n\n0000000115 00000 n\n"
            b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n190\n%%EOF"
        )
        # Should not raise even if text is empty
        result = extract_text_from_bytes(minimal_pdf, "test.pdf")
        assert isinstance(result, str)


# ── Schema Tests ──────────────────────────────────────────────────────────────

class TestSchemas:
    def test_bid_bundle_defaults(self):
        bundle = BidBundle()
        assert bundle.deal.customer == ""
        assert bundle.sizing.vm_count == 0
        assert bundle.boq.hardware == []

    def test_review_session_has_blockers(self, sample_audit):
        from app.models.schemas import ReviewSession
        session = ReviewSession(session_id="test-123", deal_name="Test Deal")
        session.audit_result = sample_audit
        assert session.has_blockers is True

    def test_review_session_no_blockers(self, sample_bundle):
        from app.models.schemas import ReviewSession, AuditResult, GovernanceScorecard
        session = ReviewSession(session_id="test-456", deal_name="Clean Deal")
        session.audit_result = AuditResult(
            scorecard=GovernanceScorecard(overall_score=90, blocker_count=0),
            issues=[],
        )
        assert session.has_blockers is False

    def test_issue_severity_enum(self):
        assert Severity.BLOCKER.value == "BLOCKER"
        assert Severity.HIGH.value == "HIGH"

    def test_verdict_enum(self):
        area = AuditArea(area="Test", verdict=Verdict.PASS, score=90)
        assert area.verdict == Verdict.PASS


# ── Prompt Tests ──────────────────────────────────────────────────────────────

class TestPrompts:
    def test_bid_bundle_prompt_contains_documents(self):
        docs = {"crm": "CRM content here", "proposal": "Proposal content here"}
        prompt = build_bid_bundle_prompt(docs)
        assert "CRM" in prompt.upper()
        assert "CRM content here" in prompt

    def test_audit_prompt_contains_bundle(self, sample_bundle):
        docs = {"proposal": "Proposal text"}
        prompt = build_audit_prompt(sample_bundle, docs)
        assert "Test Bank" in prompt
        assert "Business Fit" in prompt

    def test_rewrite_prompt_contains_issues(self, sample_bundle, sample_issue):
        prompt = build_rewrite_prompt(sample_bundle, [sample_issue], "original proposal")
        assert "INF-SIZ-001" in prompt
        assert "Increase node count" in prompt

    def test_legal_prompt_contains_sow(self, sample_bundle):
        docs = {"sow": "Unlimited SLA penalty clause"}
        prompt = build_legal_prompt(sample_bundle, docs)
        assert "Unlimited SLA penalty" in prompt


# ── AI Client Tests (mocked) ──────────────────────────────────────────────────

class TestAIClientMocked:
    def test_openai_client_success(self):
        """OpenAI client parses JSON response correctly."""
        from app.services.ai_client import OpenAIClient

        mock_response = MagicMock()
        mock_response.choices[0].message.content = '{"result": "ok"}'
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        mock_response.usage.total_tokens = 150

        with patch("openai.OpenAI") as MockClient:
            MockClient.return_value.chat.completions.create.return_value = mock_response
            client = OpenAIClient()
            client._client = MockClient.return_value
            result = client.chat("system", "user", context="test")
            assert result == {"result": "ok"}

    def test_openai_client_json_mode_strips_fences(self):
        from app.services.ai_client import _strip_fences
        raw = "```json\n{\"key\": \"value\"}\n```"
        cleaned = _strip_fences(raw)
        assert cleaned == '{"key": "value"}'

    def test_ai_response_parse_error_on_invalid_json(self):
        from app.services.ai_client import _parse_json_response
        from app.core.exceptions import AIResponseParseError
        with pytest.raises(AIResponseParseError):
            _parse_json_response("not valid json", "test")


# ── Pipeline Integration (mocked AI calls) ────────────────────────────────────

class TestPipelineMocked:
    """
    Integration tests for the full pipeline with AI calls mocked.
    These verify the pipeline orchestration without making real API calls.
    """

    def _make_bundle_response(self) -> dict:
        return {
            "deal": {"customer": "Test Corp", "industry": "Finance"},
            "requirements": {}, "solution": {}, "sizing": {},
            "boq": {}, "commercials": {}, "sow": {}, "tnc": {}
        }

    def _make_audit_response(self) -> dict:
        return {
            "scorecard": {
                "areas": [
                    {"area": "Business Fit", "verdict": "PASS", "score": 90, "issue_count": 0, "notes": ""},
                    {"area": "Sizing Validity", "verdict": "BLOCKER", "score": 40, "issue_count": 1, "notes": "Node count low"},
                ],
                "overall_score": 65,
                "blocker_count": 1,
                "recommendation": "Conditional Go",
                "clarifying_questions": ["What is the target RTO?"],
            },
            "issues": [
                {
                    "id": "INF-SIZ-001",
                    "category": "Sizing",
                    "severity": "BLOCKER",
                    "finding": "DR node count insufficient",
                    "evidence": "Sizing sheet shows 1 node",
                    "impact": "Failover will cause outage",
                    "fix": "Add 1 more node",
                    "owner": "Presales",
                    "status": "Open",
                }
            ]
        }

    def _make_rewrite_response(self) -> dict:
        return {
            "executive_summary": "Revised exec summary",
            "solution_approach": "Revised approach",
            "architecture_justification": "Architecture rationale",
            "sizing_assumptions": "Sizing notes",
            "scope_and_deliverables": "Scope",
            "milestones_and_acceptance": "Milestones",
            "dependencies": "Dependencies",
            "commercial_clarifications": "Commercial notes",
            "assumptions_and_exclusions": "Assumptions"
        }

    def _make_legal_response(self) -> dict:
        return {
            "revised_sla_clause": "SLA clause text",
            "revised_liability_clause": "Liability clause",
            "revised_change_control": "Change control process",
            "revised_acceptance_criteria": "Acceptance criteria",
            "revised_warranty_clause": "Warranty clause",
            "additional_recommendations": ["Get legal sign-off before execution"]
        }

    @pytest.mark.asyncio
    async def test_full_pipeline_mocked(self, tmp_path):
        """Full pipeline runs successfully with mocked AI calls."""
        from app.services.evaluator import BidReviewPipeline

        # Minimal valid TXT "documents"
        uploaded = {
            "crm": (b"Customer: Test Corp. Industry: Finance.", "crm.txt"),
            "requirements": (b"Must have HA. Must have DR.", "requirements.txt"),
            "sizing": (b"VM Count: 20. CPU: 4:1.", "sizing.txt"),
            "boq": (b"Hardware: Dell PowerEdge.", "boq.txt"),
            "proposal": (b"Proposed solution includes HCI.", "proposal.txt"),
        }

        pipeline = BidReviewPipeline()

        with (
            patch.object(pipeline._openai, "chat") as mock_openai,
            patch.object(pipeline._claude, "chat") as mock_claude,
            patch("app.services.output_generator.generate_all_outputs") as mock_gen,
        ):
            mock_openai.side_effect = [
                self._make_bundle_response(),
                self._make_audit_response(),
                self._make_rewrite_response(),
            ]
            mock_claude.return_value = self._make_legal_response()
            mock_gen.return_value = {
                "scorecard": "/tmp/scorecard.docx",
                "issue_log": "/tmp/issue_log.xlsx",
                "proposal": "/tmp/proposal.docx",
                "sow": "/tmp/sow.docx",
            }

            session = await pipeline.run("Test Corp — HCI Deal", uploaded)

            assert session.bid_bundle is not None
            assert session.bid_bundle.deal.customer == "Test Corp"
            assert session.audit_result is not None
            assert session.audit_result.scorecard.blocker_count == 1
            assert session.has_blockers is True
            assert session.proposal_rewrite.executive_summary == "Revised exec summary"
            assert session.legal_review.revised_sla_clause == "SLA clause text"
            assert session.is_complete is True