"""
app/services/prompts.py
────────────────────────
All AI prompts for the Bid Review Board pipeline.

Keeping prompts separate from business logic makes them easy to
version, test, and iterate without touching service code.
"""
from __future__ import annotations

import json
from app.models.schemas import BidBundle, AUDIT_AREAS


# ── Stage 2: Bid Bundle Extraction ───────────────────────────────────────────

BID_BUNDLE_SYSTEM = """You are a senior solution architect and commercial analyst.
Extract structured deal intelligence from raw proposal documents.
Return ONLY valid JSON. No markdown fences. No commentary."""

BID_BUNDLE_SCHEMA = json.dumps(
    {
        "deal": {
            "customer": "",
            "industry": "",
            "locations": [],
            "business_objective": "",
            "pain_points": [],
            "success_criteria": [],
            "timeline": "",
            "budget_signals": ""
        },
        "requirements": {
            "must_have": [],
            "should_have": [],
            "constraints": [],
            "compliance": []
        },
        "solution": {
            "architecture_type": "",
            "technologies": [],
            "dependencies": [],
            "assumptions": [],
            "exclusions": []
        },
        "sizing": {
            "workload_type": "",
            "vm_count": 0,
            "cpu_ratio": "",
            "memory_gb": 0,
            "storage_usable_tb": 0,
            "iops": 0,
            "growth_pct": 0,
            "ha_model": ""
        },
        "boq": {
            "hardware": [],
            "software": [],
            "licenses": [],
            "support": [],
            "services": []
        },
        "commercials": {
            "deal_value": "",
            "discount_pct": 0,
            "margin_pct": 0,
            "payment_terms": "",
            "validity_days": 0
        },
        "sow": {
            "deliverables": [],
            "milestones": [],
            "acceptance_criteria": [],
            "customer_responsibilities": []
        },
        "tnc": {
            "liability_cap": "",
            "warranty": "",
            "sla_summary": "",
            "penalties": "",
            "change_control": ""
        }
    },
    indent=2
)


def build_bid_bundle_prompt(documents: dict[str, str]) -> str:
    docs_text = "\n\n".join(
        f"=== {label.upper()} ===\n{content}"
        for label, content in documents.items()
        if content.strip()
    )
    return f"""Extract structured deal intelligence from the following documents.

Return a single JSON object matching this exact schema:
{BID_BUNDLE_SCHEMA}

Fill every field as accurately as possible from the documents.
Use empty strings / empty arrays where information is not available.
Do NOT invent information not present in the documents.

DOCUMENTS:
{docs_text}"""


# ── Stage 3: Governance Audit ─────────────────────────────────────────────────

AUDIT_SYSTEM = """You are the Tech9Labs AI Bid Review Board.
You act simultaneously as: Delivery Head, Chief Architect, Commercial Controller, and Solution Assurance Director.

Your job is to PREVENT proposals from reaching customers with errors, oversell, undersizing, or legal risk.
Be strict. Be evidence-based. Do NOT summarise. Do NOT be polite.

Return ONLY valid JSON. No markdown. No commentary outside JSON."""

AUDIT_SCHEMA = json.dumps(
    {
        "scorecard": {
            "areas": [
                {
                    "area": "<area name>",
                    "verdict": "PASS | REVIEW | BLOCKER",
                    "score": 0,
                    "issue_count": 0,
                    "notes": ""
                }
            ],
            "overall_score": 0,
            "blocker_count": 0,
            "recommendation": "Go | Conditional Go | No Go",
            "clarifying_questions": []
        },
        "issues": [
            {
                "id": "CAT-SUB-NNN",
                "category": "Sizing | Architecture | BOQ | Legal | Commercial | Scope | Delivery | Business Fit | Requirements | Operability",
                "severity": "BLOCKER | HIGH | MEDIUM | LOW | INFO",
                "finding": "",
                "evidence": "",
                "impact": "",
                "fix": "",
                "owner": "Presales | Delivery | Legal | Commercial",
                "status": "Open"
            }
        ]
    },
    indent=2
)


def build_audit_prompt(bid_bundle: BidBundle, documents: dict[str, str]) -> str:
    bundle_json = bid_bundle.model_dump_json(indent=2)

    docs_summary = "\n\n".join(
        f"=== {label.upper()} ===\n{content[:3000]}"
        for label, content in documents.items()
        if content.strip()
    )

    areas_list = "\n".join(f"- {a}" for a in AUDIT_AREAS)

    return f"""Perform a full governance audit of this proposal.

AUDIT AREAS (check ALL of these):
{areas_list}

AUDIT INSTRUCTIONS:
1. Cross-verify CRM promises vs proposal vs SOW vs BOQ vs sizing.
2. Detect missing scope, missing deliverables, hidden dependencies.
3. Validate architecture supports stated HA, DR, performance, scalability.
4. Validate sizing headroom, CPU ratio, memory, storage, and growth assumptions.
5. Verify BOQ contains every required component mentioned in SOW or solution.
6. Identify commercial risks: margin, payment exposure, discount.
7. Identify legal and SLA risks: liability caps, penalty clauses, ambiguous language.
8. Identify customer expectation mismatches.
9. Provide structured findings ONLY with direct evidence from documents.

SCORING (per area):
- 90–100: No issues
- 75–89: Minor gaps
- 60–74: Moderate gaps, REVIEW required
- Below 60: Significant failure, BLOCKER

ISSUE ID FORMAT: <CATEGORY_CODE>-<SUB>-<NNN>
Examples: INF-SIZ-001, ARCH-HA-002, LEG-SLA-003, COM-BOQ-004

BID BUNDLE (structured deal data):
{bundle_json}

DOCUMENT CONTENT:
{docs_summary}

Return JSON matching this schema exactly:
{AUDIT_SCHEMA}"""


# ── Stage 4: Proposal Rewrite ─────────────────────────────────────────────────

REWRITE_SYSTEM = """You are the Lead Solution Architect and Delivery Director at Tech9Labs.
Rewrite and fix proposal sections based on audit findings.
Write customer-ready, professional text suitable for direct inclusion in a formal proposal.
Return ONLY valid JSON. No markdown fences."""

REWRITE_SCHEMA = json.dumps(
    {
        "executive_summary": "",
        "solution_approach": "",
        "architecture_justification": "",
        "sizing_assumptions": "",
        "scope_and_deliverables": "",
        "milestones_and_acceptance": "",
        "dependencies": "",
        "commercial_clarifications": "",
        "assumptions_and_exclusions": ""
    },
    indent=2
)


def build_rewrite_prompt(
    bid_bundle: BidBundle,
    audit_issues: list,
    original_proposal: str,
) -> str:
    bundle_json = bid_bundle.model_dump_json(indent=2)

    issues_text = "\n".join(
        f"[{i.severity.value}] {i.id} — {i.finding}\n  Fix: {i.fix}"
        for i in audit_issues
    )

    return f"""Rewrite the proposal sections to fix all identified issues.

ISSUES TO FIX:
{issues_text}

DEAL CONTEXT (Bid Bundle):
{bundle_json}

ORIGINAL PROPOSAL (for reference):
{original_proposal[:4000]}

INSTRUCTIONS:
- Fix every issue in the rewrite.
- Write in formal, customer-facing English.
- Be specific — include actual sizing numbers, architecture names, milestones.
- Do NOT add fluff or generic consulting language.
- Each section should be 2–5 concise paragraphs.

Return JSON matching this schema exactly:
{REWRITE_SCHEMA}"""


# ── Stage 5: Legal Review (Claude) ────────────────────────────────────────────

LEGAL_SYSTEM = """You are a senior technology contract reviewer specialising in IT services and infrastructure delivery agreements.
Your job is to rewrite contract clauses to be legally safe, unambiguous, and fair — while remaining customer-friendly.
Return ONLY valid JSON. No markdown. No preamble."""

LEGAL_SCHEMA = json.dumps(
    {
        "revised_sla_clause": "",
        "revised_liability_clause": "",
        "revised_change_control": "",
        "revised_acceptance_criteria": "",
        "revised_warranty_clause": "",
        "additional_recommendations": []
    },
    indent=2
)


def build_legal_prompt(bid_bundle: BidBundle, documents: dict[str, str]) -> str:
    bundle_json = bid_bundle.model_dump_json(indent=2)

    sow_text = documents.get("sow", "")
    tnc_text = documents.get("tnc", documents.get("terms", ""))

    return f"""Review and rewrite the SOW and Terms & Conditions clauses.

REWRITE OBJECTIVES:
1. Remove all ambiguity from SLA definitions.
2. Add a limitation of liability clause capped at contract value.
3. Define clear change request / change control process.
4. Define unambiguous acceptance criteria with sign-off timelines.
5. Tighten warranty language to specific duration and scope.
6. Cap SLA penalty credits at maximum 10% of annual contract value.
7. Ensure customer responsibilities are clearly listed to protect Tech9Labs.
8. Make language customer-friendly but legally protective.

DEAL CONTEXT:
{bundle_json}

SOW TEXT:
{sow_text[:3000] if sow_text else "Not provided — generate standard clauses based on deal context."}

TERMS & CONDITIONS:
{tnc_text[:3000] if tnc_text else "Not provided — generate standard clauses based on deal context."}

Return JSON matching this schema exactly:
{LEGAL_SCHEMA}"""