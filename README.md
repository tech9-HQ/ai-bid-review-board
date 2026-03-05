# Tech9Labs AI Bid Review Board — v1 Backend

Production-ready FastAPI backend for automated proposal governance.  
Every proposal passes through 6 AI stages before it can reach a customer.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    FastAPI Application                          │
│                                                                 │
│  POST /evaluate/          POST /evaluate/quick/                 │
│         │                        │                             │
│         ▼                        ▼                             │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              BidReviewPipeline (evaluator.py)           │   │
│  │                                                         │   │
│  │  Stage 1: Document Extract  (parser.py)                 │   │
│  │  Stage 2: Bid Bundle Build  (OpenAI GPT-4o)             │   │
│  │  Stage 3: Governance Audit  (OpenAI GPT-4o)             │   │
│  │  Stage 4: Proposal Rewrite  (OpenAI GPT-4o)             │   │
│  │  Stage 5: Legal Review      (Anthropic Claude)          │   │
│  │  Stage 6: Publish Outputs   (DOCX + XLSX generation)    │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  GET  /outputs/{session_id}/{filename}  — File download         │
│  GET  /sessions/                        — Session history       │
│  GET  /health/                          — Health check          │
└─────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
ai-bid-review-board/
├── main.py                      # App factory + entry point
├── requirements.txt
├── .env.example
├── pytest.ini
│
├── app/
│   ├── api/
│   │   └── routes.py            # All API endpoints
│   │
│   ├── core/
│   │   ├── config.py            # Settings (pydantic-settings)
│   │   ├── exceptions.py        # Custom exceptions + handlers
│   │   └── logging.py           # Loguru structured logging
│   │
│   ├── models/
│   │   └── schemas.py           # All Pydantic schemas
│   │
│   ├── services/
│   │   ├── parser.py            # PDF/DOCX/XLSX text extraction
│   │   ├── prompts.py           # All AI prompts (versioned here)
│   │   ├── ai_client.py         # OpenAI + Anthropic wrappers
│   │   ├── evaluator.py         # 6-stage pipeline orchestrator
│   │   └── output_generator.py  # DOCX/XLSX generation
│   │
│   └── utils/
│       └── file_utils.py        # Upload validation helpers
│
└── tests/
    └── test_evaluator.py        # Full test suite
```

---

## Quick Start

### 1. Clone & Set Up Environment

```bash
git clone <repo>
cd ai-bid-review-board

python -m venv venv
# Windows:
venv\Scripts\Activate.ps1
# macOS/Linux:
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your API keys:
#   OPENAI_API_KEY=sk-...
#   ANTHROPIC_API_KEY=sk-ant-...
```

### 3. Run Locally

```bash
uvicorn main:app --reload
```

API is available at: http://localhost:8000  
Swagger docs: http://localhost:8000/docs

---

## API Endpoints

### POST `/evaluate/` — Full 6-Stage Review

Upload all deal documents for complete AI governance review.

**Form fields:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `deal_name` | string | ✅ | Customer / deal name |
| `crm` | file | ✅ | CRM snapshot (PDF/DOCX/TXT) |
| `requirements` | file | ✅ | Requirements / MoM |
| `sizing` | file | ✅ | Sizing workbook (XLSX/PDF) |
| `boq` | file | ✅ | Bill of Quantities |
| `proposal` | file | ✅ | Draft proposal (PDF/DOCX) |
| `commercial` | file | ❌ | Commercial sheet |
| `sow` | file | ❌ | Statement of Work |
| `tnc` | file | ❌ | Terms & Conditions |

**Example (curl):**
```bash
curl -X POST http://localhost:8000/evaluate/ \
  -F "deal_name=Al Rajhi Bank — HCI Phase 2" \
  -F "crm=@./crm.pdf" \
  -F "requirements=@./requirements.docx" \
  -F "sizing=@./sizing.xlsx" \
  -F "boq=@./boq.xlsx" \
  -F "proposal=@./proposal.docx" \
  -F "sow=@./sow.docx"
```

**Response:**
```json
{
  "success": true,
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "has_blockers": true,
  "recommendation": "Conditional Go",
  "bid_bundle": { ... },
  "audit_result": {
    "scorecard": {
      "overall_score": 67,
      "blocker_count": 1,
      "areas": [ ... ]
    },
    "issues": [
      {
        "id": "INF-SIZ-004",
        "severity": "BLOCKER",
        "finding": "DR failover node capacity insufficient",
        "fix": "Increase node count to 4"
      }
    ]
  },
  "output_files": {
    "scorecard": "/outputs/{session_id}/Board_Scorecard.docx",
    "issue_log": "/outputs/{session_id}/Issue_Log.xlsx",
    "proposal": "/outputs/{session_id}/Proposal_Revised_v1.docx",
    "sow":      "/outputs/{session_id}/SOW_Revised_v1.docx"
  }
}
```

### POST `/evaluate/quick/` — Fast 2-Document Check (Stages 1-3 only)

```bash
curl -X POST http://localhost:8000/evaluate/quick/ \
  -F "deal_name=Quick Check" \
  -F "rfp=@./rfp.pdf" \
  -F "proposal=@./proposal.pdf"
```

### GET `/outputs/{session_id}/{filename}` — Download Output File

```bash
curl -O http://localhost:8000/outputs/{session_id}/Board_Scorecard.docx
```

---

## Output Documents

| File | Contents |
|------|----------|
| `Board_Scorecard.docx` | 10-area governance scorecard + full issue log table |
| `Issue_Log.xlsx` | Machine-readable findings (colour-coded by severity) |
| `Proposal_Revised_v1.docx` | AI-rewritten proposal with all issues fixed |
| `SOW_Revised_v1.docx` | Claude-reviewed legal clauses |

---

## Governance Areas Checked

| # | Area | What's Validated |
|---|------|-----------------|
| 1 | Business Fit | Pain points solved by architecture |
| 2 | Requirements Traceability | Every requirement in solution or exclusions |
| 3 | Architecture Integrity | HA, DR, performance, scalability |
| 4 | Sizing Validity | CPU ratio, memory, storage, growth headroom |
| 5 | BOQ Consistency | All solution components in BOQ |
| 6 | Scope Completeness | All deliverables defined |
| 7 | Delivery Risk | Dependencies and assumptions declared |
| 8 | Commercial Safety | Margin, payment terms, discount |
| 9 | Legal Risk | SLA caps, liability, penalty clauses |
| 10 | Operability | Support, monitoring, handover plan |

---

## Running Tests

```bash
pytest tests/ -v
pytest tests/ -v --cov=app --cov-report=term-missing
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | OpenAI API key (required) |
| `ANTHROPIC_API_KEY` | — | Anthropic API key (required) |
| `OPENAI_AUDIT_MODEL` | `gpt-4o` | Model for audit + bundle stages |
| `OPENAI_REWRITE_MODEL` | `gpt-4o` | Model for rewrite stage |
| `CLAUDE_LEGAL_MODEL` | `claude-opus-4-6` | Claude model for legal review |
| `AI_TEMPERATURE` | `0.2` | Temperature for all AI calls |
| `AI_MAX_TOKENS` | `4096` | Max tokens per AI response |
| `MAX_UPLOAD_SIZE_MB` | `50` | Max file upload size |
| `UPLOAD_DIR` | `./uploads` | Temporary upload directory |
| `OUTPUT_DIR` | `./outputs` | Generated document directory |
| `APP_ENV` | `development` | `development` / `production` |
| `SENTRY_DSN` | — | Optional Sentry error tracking DSN |
| `ALLOWED_ORIGINS` | `localhost:3000` | CORS origins (comma-separated) |

---

## Production Deployment

### Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

### Recommended Production Settings

```bash
# Use gunicorn with uvicorn workers for multi-process
pip install gunicorn
gunicorn main:app -w 2 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

---

## Extending the Pipeline

To add a new stage:
1. Add a new `StageStatus` entry in `ReviewSession.stages` (schemas.py)
2. Write the stage method in `BidReviewPipeline` (evaluator.py)
3. Add the prompt in `prompts.py`
4. Call it from `BidReviewPipeline.run()`

To change AI models:
- Update `.env` — no code changes needed.

To add new document types:
- Update `SUPPORTED_EXTENSIONS` in `parser.py`
- Add extraction logic in the appropriate `_extract_*` function.