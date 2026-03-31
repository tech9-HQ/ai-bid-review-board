"""
app/services/prompts.py
────────────────────────
All AI prompts for the bid review pipeline.

Design principles:
  - System prompts define persona and output contract.
  - User prompts inject document content via XML tags (<document> blocks).
  - All structured-output prompts specify exact JSON schema in the system prompt.
  - Claude-specific: uses XML tags for document injection (better than plain
    text for Claude's attention mechanism).
  - Versioned in this file — change prompt behaviour here, not in evaluator.py.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.models.schemas import AuditResult, BidBundle


class BidPrompts:
    """
    Container for all pipeline prompts.
    System prompts are class-level constants.
    Builder methods construct user-turn prompts with document content.
    """

    # ── System Prompts ─────────────────────────────────────────────────────

    BUNDLE_SYSTEM = """You are a senior pre-sales architect at a technology solutions company.
Your task is to read a set of deal documents and extract a structured bid bundle summary.

Output a single JSON object with this exact schema:
{
  "deal_name": "string",
  "customer": "string",
  "solution_summary": "string (2-3 sentences)",
  "architecture_components": ["string"],
  "total_value_usd": number_or_null,
  "delivery_timeline_weeks": number_or_null,
  "key_risks": ["string"],
  "assumptions": ["string"],
  "exclusions": ["string"],
  "requirements_coverage": {
    "covered": ["string"],
    "gaps": ["string"]
  }
}

Be precise and factual. Extract only what is stated in the documents."""

    AUDIT_SYSTEM = """You are a bid governance auditor. Your role is to identify issues that would
block or conditionally approve a proposal before it reaches a customer.

Evaluate across exactly 10 areas. For each issue found, assign one severity:
  BLOCKER  — must be fixed before submission
  MAJOR    — should be fixed; affects score significantly
  MINOR    — improvement recommended

Output a single JSON object with this exact schema:
{
  "scorecard": {
    "overall_score": integer_0_to_100,
    "blocker_count": integer,
    "major_count": integer,
    "minor_count": integer,
    "areas": [
      {
        "id": "string (e.g. GOV-01)",
        "name": "string",
        "score": integer_0_to_10,
        "status": "pass|warn|fail"
      }
    ]
  },
  "issues": [
    {
      "id": "string (e.g. INF-SIZ-004)",
      "area": "string",
      "severity": "BLOCKER|MAJOR|MINOR",
      "finding": "string — what is wrong",
      "fix": "string — what to do",
      "reference_doc": "string — which document this was found in"
    }
  ],
  "executive_summary": "string (3-5 sentences for board)"
}"""

    REWRITE_SYSTEM = """You are a senior technical writer at a technology solutions company.
You will receive a draft proposal and a list of governance issues that must be addressed.
Rewrite the proposal in clean, professional English, incorporating all required fixes.

Output the revised proposal as structured text with clear section headings.
Do not include JSON. Do not mention the audit or governance process in the output.
Write as if this is the original polished proposal."""

    LEGAL_SYSTEM = """You are a technology contracts lawyer specialising in IT services agreements.
Review the provided legal documents (SOW, T&C, commercial terms) for risk clauses.

Output a single JSON object with this exact schema:
{
  "summary": "string (2-3 sentences)",
  "risk_level": "low|medium|high|critical",
  "clauses": [
    {
      "clause_ref": "string",
      "document": "string",
      "risk_type": "liability|sla|payment|ip|termination|other",
      "risk_level": "low|medium|high|critical",
      "description": "string",
      "recommendation": "string"
    }
  ],
  "recommended_changes": [
    {
      "clause_ref": "string",
      "current_text_summary": "string",
      "proposed_change": "string",
      "rationale": "string"
    }
  ],
  "show_stoppers": ["string"]
}"""

    # ── User Prompt Builders ───────────────────────────────────────────────

    def build_bundle(self, extracted: Dict[str, str], deal_name: str) -> str:
        """Build Stage 2 user prompt — bid bundle extraction."""
        doc_block = self._format_documents(extracted)
        return f"""Deal name: {deal_name}

Analyse the following deal documents and extract a structured bid bundle.

{doc_block}

Return the JSON bid bundle object."""

    def governance_audit(self, bundle: BidBundle, extracted: Dict[str, str]) -> str:
        """Build Stage 3 user prompt — governance audit."""
        doc_block = self._format_documents(extracted)
        return f"""Bid bundle summary:
<bid_bundle>
{bundle.model_dump_json(indent=2)}
</bid_bundle>

Full document set:
{doc_block}

The 10 governance areas to evaluate are:
1. Business Fit — do pain points map to the proposed solution?
2. Requirements Traceability — every requirement is covered or explicitly excluded
3. Architecture Integrity — HA, DR, performance, scalability validated
4. Sizing Validity — CPU/memory/storage ratios, growth headroom
5. BOQ Consistency — all solution components appear in the BOQ
6. Scope Completeness — all deliverables explicitly defined
7. Delivery Risk — dependencies and assumptions declared
8. Commercial Safety — margin, payment terms, discount policy
9. Legal Risk — SLA caps, liability clauses, penalty exposure
10. Operability — support model, monitoring, handover plan

Return the JSON audit result object."""

    def rewrite_proposal(
        self,
        bundle: BidBundle,
        audit: AuditResult,
        extracted: Dict[str, str],
    ) -> str:
        """Build Stage 4 user prompt — proposal rewrite."""
        original = extracted.get("proposal", "")
        issues_json = [i.model_dump() for i in audit.issues]

        return f"""Original proposal:
<original_proposal>
{original[:8000]}
</original_proposal>

Governance issues to address:
<issues>
{issues_json}
</issues>

Bid bundle context:
<context>
Deal: {bundle.deal_name}
Customer: {bundle.customer}
Solution: {bundle.solution_summary}
</context>

Rewrite the proposal incorporating all fixes. Maintain professional tone throughout."""

    def legal_review(
        self,
        sow_text: str,
        tnc_text: str,
        commercial_text: str,
    ) -> str:
        """Build Stage 5 user prompt — legal review."""
        parts = []
        if sow_text:
            parts.append(f"<sow>\n{sow_text[:6000]}\n</sow>")
        if tnc_text:
            parts.append(f"<terms_and_conditions>\n{tnc_text[:6000]}\n</terms_and_conditions>")
        if commercial_text:
            parts.append(f"<commercial_terms>\n{commercial_text[:4000]}\n</commercial_terms>")

        docs = "\n\n".join(parts)
        return f"""Review the following contract documents for legal and commercial risk.

{docs}

Identify all risk clauses and return the JSON legal review object."""

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _format_documents(extracted: Dict[str, str]) -> str:
        """
        Format extracted document text into Claude-friendly XML blocks.
        Truncates very long documents to stay within context limits.
        """
        MAX_CHARS_PER_DOC = 8000
        blocks = []
        for doc_type, content in extracted.items():
            if content and content.strip():
                truncated = content[:MAX_CHARS_PER_DOC]
                if len(content) > MAX_CHARS_PER_DOC:
                    truncated += f"\n[... truncated — {len(content) - MAX_CHARS_PER_DOC} chars omitted ...]"
                blocks.append(f"<{doc_type}>\n{truncated}\n</{doc_type}>")

        return "\n\n".join(blocks) if blocks else "<documents>No documents provided.</documents>"