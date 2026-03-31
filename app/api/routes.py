"""
app/api/routes.py
──────────────────
All API endpoints for the Bid Review Board.

POST /evaluate/
    → Runs Stages 1–5. Returns full results for on-screen display.
      No documents are generated. Session is stored in memory.

POST /sessions/{session_id}/generate-docs/
    → Triggers Stage 6 on a previously reviewed session.
      Generates Board_Scorecard.docx, Issue_Log.xlsx,
      Proposal_Revised_v1.docx, SOW_Revised_v1.docx.
      Returns download URLs.

GET  /sessions/{session_id}/
    → Retrieve results for a previous session (for page refresh / sharing).

GET  /outputs/{session_id}/{filename}
    → Download a generated document file.

GET  /sessions/
    → List recent sessions.

GET  /health/
    → Health check.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from loguru import logger

from app.core.config import settings
from app.models.schemas import (
    EvaluationResponse,
)
from app.services.evaluator import BidReviewPipeline, _session_store
from app.utils.file_utils import read_upload_file, sanitise_deal_name

router = APIRouter()
pipeline = BidReviewPipeline()


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/health/", tags=["System"])
async def health_check() -> dict:
    return {
        "status": "ok",
        "version": settings.APP_VERSION,
        "env": settings.APP_ENV,
    }


# ── Evaluate (Stages 1-5, results only) ──────────────────────────────────────

@router.post("/evaluate/", response_model=EvaluationResponse, tags=["Evaluation"])
async def evaluate(
    deal_name: str = Form(..., description="Customer / deal name"),
    crm: UploadFile = File(..., description="CRM snapshot (PDF/DOCX/TXT)"),
    requirements: UploadFile = File(..., description="Requirements / MoM (PDF/DOCX/TXT)"),
    sizing: UploadFile = File(..., description="Sizing workbook (XLSX/PDF)"),
    boq: UploadFile = File(..., description="Bill of Quantities (XLSX/PDF/DOCX)"),
    proposal: UploadFile = File(..., description="Draft proposal (PDF/DOCX)"),
    commercial: UploadFile | None = File(None, description="Commercial sheet (optional)"),
    sow: UploadFile | None = File(None, description="Statement of Work (optional)"),
    tnc: UploadFile | None = File(None, description="Terms & Conditions (optional)"),
):
    """
    Submit a deal for AI Bid Review Board evaluation (Stages 1-5).

    Returns structured results immediately for on-screen display:
    - Bid Bundle (deal intelligence)
    - Governance Scorecard (10 areas, Pass/Review/Blocker)
    - Issue Log (all findings with fixes)
    - Proposal Rewrite (corrected sections)
    - Legal Review (if Anthropic key configured)

    The session is saved in memory. To generate downloadable DOCX/XLSX
    documents, call POST /sessions/{session_id}/generate-docs/ afterwards.
    """
    deal_name = sanitise_deal_name(deal_name)
    logger.info(f"[API] POST /evaluate/ | deal={deal_name}")

    uploaded: dict[str, tuple[bytes, str]] = {}

    for role, upload in {
        "crm": crm,
        "requirements": requirements,
        "sizing": sizing,
        "boq": boq,
        "proposal": proposal,
    }.items():
        uploaded[role] = await read_upload_file(upload)

    for role, upload in {
        "commercial": commercial,
        "sow": sow,
        "tnc": tnc,
    }.items():
        if upload is not None:
            uploaded[role] = await read_upload_file(upload)

    session = await pipeline.run(deal_name, uploaded)

    return EvaluationResponse(
        success=True,
        session_id=session.session_id,
        deal_name=session.deal_name,
        bid_bundle=session.bid_bundle,
        audit_result=session.audit_result,
        proposal_rewrite=session.proposal_rewrite,
        legal_review=session.legal_review,
        has_blockers=session.has_blockers,
        recommendation=session.audit_result.scorecard.recommendation,
        stages=session.stages,
    )


# ── Generate Documents (Stage 6, on demand) ───────────────────────────────────

@router.post(
    "/sessions/{session_id}/generate-docs/",
    tags=["Documents"],
)
async def generate_docs(session_id: str):
    """
    Generate downloadable DOCX/XLSX documents for a reviewed session.

    Call this after reviewing results on screen via POST /evaluate/.
    Idempotent — calling it twice returns the same files without regenerating.

    Generates:
    - Board_Scorecard.docx       Governance scorecard + issue log
    - Issue_Log.xlsx             Colour-coded findings register
    - Proposal_Revised_v1.docx   AI-rewritten proposal
    - SOW_Revised_v1.docx        Legal-reviewed SOW clauses
    """
    logger.info(f"[API] POST /sessions/{session_id}/generate-docs/")

    session = pipeline.generate_documents(session_id)

    output_urls = {
        role: f"/outputs/{session.session_id}/{Path(path).name}"
        for role, path in session.output_files.items()
    }

    return {
    "success": True,
    "session_id": session.session_id,
    "output_files": output_urls,
}


# ── Get Session Results ────────────────────────────────────────────────────────

@router.get("/sessions/{session_id}/", response_model=EvaluationResponse, tags=["Evaluation"])
async def get_session(session_id: str):
    """
    Retrieve the results of a previous review session by ID.
    Useful for page refresh or sharing a result link.
    """
    session = _session_store.get(session_id)
    if session is None:
        return JSONResponse(
            status_code=404,
            content={
                "success": False,
                "error": {
                    "code": "SESSION_NOT_FOUND",
                    "message": f"Session '{session_id}' not found.",
                    "detail": "Sessions live in memory. Re-submit if the server was restarted.",
                },
            },
        )

    return EvaluationResponse(
        success=True,
        session_id=session.session_id,
        deal_name=session.deal_name,
        bid_bundle=session.bid_bundle,
        audit_result=session.audit_result,
        proposal_rewrite=session.proposal_rewrite,
        legal_review=session.legal_review,
        has_blockers=session.has_blockers,
        recommendation=session.audit_result.scorecard.recommendation,
        stages=session.stages,
    )


# ── List Sessions ─────────────────────────────────────────────────────────────

@router.get("/sessions/", tags=["System"])
async def list_sessions():
    """List all active in-memory sessions."""
    return {
        "count": len(_session_store),
        "sessions": [
            {
                "session_id": sid,
                "deal_name": s.deal_name,
                "has_blockers": s.has_blockers,
                "recommendation": s.audit_result.scorecard.recommendation.value
                    if s.audit_result else "pending",
                "docs_generated": bool(s.output_files),
                "overall_score": s.audit_result.scorecard.overall_score
                    if s.audit_result else 0,
            }
            for sid, s in _session_store.items()
        ],
    }


# ── Download Output File ──────────────────────────────────────────────────────

@router.get("/outputs/{session_id}/{filename}", tags=["Documents"])
async def download_output(session_id: str, filename: str):
    """Download a generated output document by session ID and filename."""
    safe_session = session_id.replace("..", "").replace("/", "").replace("\\", "")
    safe_file = filename.replace("..", "").replace("/", "").replace("\\", "")

    file_path = settings.OUTPUT_DIR / safe_session / safe_file

    if not file_path.exists():
        return JSONResponse(
            status_code=404,
            content={
                "success": False,
                "error": {
                    "message": "File not found.",
                    "detail": "Generate documents first via POST /sessions/{id}/generate-docs/",
                },
            },
        )

    return FileResponse(
        path=str(file_path),
        filename=safe_file,
        media_type="application/octet-stream",
    )