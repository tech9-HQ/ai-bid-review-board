# AI Bid Review Board – V1

Backend-only MVP for automated RFP vs Proposal evaluation using LLM.

## Features
- Upload RFP & Proposal (PDF)
- AI-based structured evaluation
- Score (0–100)
- Strengths / Weaknesses
- Risk flags
- Go / Conditional Go / No Go

## Tech Stack
- FastAPI
- OpenAI GPT-4o-mini
- PyPDF
- Python 3.11

## Run Locally

```bash
python -m venv venv
venv\Scripts\Activate
pip install -r requirements.txt
uvicorn main:app --reload