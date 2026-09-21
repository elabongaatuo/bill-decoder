"""
SMS question-answering: matches a free-text question to a bill, then answers
using only that bill's decoded content. Uses Gemini 2.5 Flash.

This reuses the cached decoded_en/sections data rather than re-decoding from
scratch each time, to keep latency and cost down for near-real-time SMS replies.
"""

import json
import os
from typing import Optional

from dotenv import load_dotenv
load_dotenv()  # so GEMINI_API_KEY is available even when this file is run directly

from google import genai
from google.genai import types
from sqlalchemy.orm import Session

from gemini_utils import call_gemini_with_retry
from models import Bill, SmsQuery

MODEL = "gemini-3.1-flash-lite"

MATCH_SYSTEM_PROMPT = """You match a citizen's SMS question to the single most \
relevant bill from a short list. Respond with ONLY the numeric ID of the best \
matching bill, or the literal word NONE if nothing matches well enough to be \
useful. No other text, no punctuation, no JSON — just the ID or NONE."""

ANSWER_SYSTEM_PROMPT = """You answer a citizen's question about a specific \
Kenyan bill, using ONLY the provided bill summary and section data. Keep the \
answer short enough for SMS (aim for under 300 characters). Always end with a \
source reference in parentheses, e.g. "(Section 14(3))". If the bill data \
does not actually answer the question, say so plainly instead of guessing — \
do not invent information not present in the provided data."""


def match_question_to_bill(question: str, db: Session, api_key: Optional[str] = None) -> Optional[Bill]:
    bills = db.query(Bill).order_by(Bill.created_at.desc()).limit(10).all()
    if not bills:
        return None

    listing = "\n".join(
        f"{b.id}: {b.title} — {(b.decoded_en or {}).get('what_it_is', '')}"
        for b in bills
    )

    client = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY"))
    response = call_gemini_with_retry(
        client,
        model=MODEL,
        contents=f"Bills:\n{listing}\n\nQuestion: {question}",
        config=types.GenerateContentConfig(
            system_instruction=MATCH_SYSTEM_PROMPT,
            max_output_tokens=20,
        ),
    )

    raw = response.text.strip()
    if raw == "NONE":
        return None

    try:
        bill_id = int(raw)
    except ValueError:
        return None

    return db.query(Bill).filter(Bill.id == bill_id).first()


def answer_question(question: str, bill: Bill, api_key: Optional[str] = None) -> str:
    context = json.dumps(bill.decoded_en or {})

    client = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY"))
    response = call_gemini_with_retry(
        client,
        model=MODEL,
        contents=f"Bill data:\n{context}\n\nQuestion: {question}",
        config=types.GenerateContentConfig(
            system_instruction=ANSWER_SYSTEM_PROMPT,
            max_output_tokens=300,
        ),
    )
    return response.text.strip()


def handle_sms_question(phone_number: str, question: str, db: Session) -> str:
    """Full pipeline: match -> answer -> log. Returns the SMS reply text."""
    bill = match_question_to_bill(question, db)

    if bill is None:
        answer = "Sorry, I couldn't match your question to a bill we're tracking. Reply MENU for a list of bills."
        db.add(SmsQuery(phone_number=phone_number, bill_id=None, question_text=question, answer_text=answer))
        db.commit()
        return answer

    answer = answer_question(question, bill)
    db.add(SmsQuery(phone_number=phone_number, bill_id=bill.id, question_text=question, answer_text=answer))
    db.commit()
    return answer