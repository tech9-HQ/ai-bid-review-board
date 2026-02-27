import os
import json
import re
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def evaluate_proposal(rfp_text: str, proposal_text: str):
    """
    Compares RFP and Proposal text and returns structured evaluation JSON.
    """

    prompt = f"""
You are an expert AI Bid Review Board.

Carefully compare the RFP and the Proposal.

Evaluate alignment, completeness, risk, and compliance.

Return ONLY valid JSON in this exact format:

{{
  "overall_score": 0-100,
  "strengths": [],
  "weaknesses": [],
  "missing_points": [],
  "risk_flags": [],
  "recommendation": "Go / Conditional Go / No Go"
}}

Scoring Logic:
- 90–100: Excellent alignment, minimal risk
- 75–89: Good alignment, minor gaps
- 60–74: Moderate gaps
- Below 60: Significant issues

RFP:
{rfp_text}

Proposal:
{proposal_text}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # You can upgrade later
            messages=[
                {"role": "system", "content": "You are a strict bid evaluation committee."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
        )

        raw_output = response.choices[0].message.content

        # Remove markdown code fences if model adds them
        cleaned_output = re.sub(r"```json|```", "", raw_output).strip()

        # Convert string JSON → Python dict
        parsed_output = json.loads(cleaned_output)

        return parsed_output

    except json.JSONDecodeError:
        return {
            "error": "Model returned invalid JSON format",
            "raw_output": raw_output
        }

    except Exception as e:
        return {
            "error": str(e)
        }