from fastapi import FastAPI, UploadFile, File
import shutil
from parser import extract_text
from evaluator import evaluate_proposal

app = FastAPI()

@app.post("/evaluate/")
async def evaluate(rfp: UploadFile = File(...), proposal: UploadFile = File(...)):

    with open("rfp.pdf", "wb") as buffer:
        shutil.copyfileobj(rfp.file, buffer)

    with open("proposal.pdf", "wb") as buffer:
        shutil.copyfileobj(proposal.file, buffer)

    rfp_text = extract_text("rfp.pdf")
    proposal_text = extract_text("proposal.pdf")

    result = evaluate_proposal(rfp_text, proposal_text)

    return {"evaluation": result}