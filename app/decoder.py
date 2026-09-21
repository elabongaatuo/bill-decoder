"""
Core decode pipeline: bill text -> structured plain-language explanation.
Uses Gemini 2.5 Flash (free tier: ~1,500 requests/day via Google AI Studio).

Run standalone for a quick test:
    python app/decoder.py
"""

import json
import os
from dataclasses import dataclass, asdict
from typing import Optional

from dotenv import load_dotenv
load_dotenv()  # so GEMINI_API_KEY is available even when this file is run directly

from google import genai
from google.genai import types

from gemini_utils import call_gemini_with_retry

MODEL = "gemini-3.1-flash-lite"

DECODE_SYSTEM_PROMPT = """You are a civic-tech assistant that decodes Kenyan \
parliamentary bills into plain language for ordinary citizens with no legal \
background. You must be strictly faithful to the source text — never invent \
dates, sections, or effects that are not in the bill. If something is unclear \
or not stated, say so explicitly rather than guessing.

Respond with ONLY a JSON object matching this exact schema:

{
  "title": "short plain-language title for the bill",
  "what_it_is": "2-3 plain sentences: what this bill actually changes",
  "who_it_affects": "1-2 plain sentences: who is impacted and how",
  "why_it_matters": "1-2 plain sentences: the practical stakes for ordinary people",
  "key_dates": [
    {"label": "short description of what happens", "detail": "date or deadline as stated in the bill, quoted faithfully"}
  ],
  "what_you_can_do": [
    {"action": "short imperative action", "where": "where/how to do it, as stated in the bill"}
  ],
  "sections": [
    {
      "official_text": "the exact clause or a close paraphrase of it, kept short",
      "plain_explanation": "1-2 sentences explaining what this clause means in practice",
      "source_ref": "the section/subsection number, e.g. 'Section 14(3)'"
    }
  ]
}

Include one "sections" entry per substantive clause (skip pure title/preliminary \
boilerplate). For a very long bill, cover the most consequential ~15-20 clauses \
rather than every single one. If key_dates or what_you_can_do have nothing to \
report, return an empty list for that field rather than inventing content."""


@dataclass
class DecodeResult:
    title: str
    what_it_is: str
    who_it_affects: str
    why_it_matters: str
    key_dates: list
    what_you_can_do: list
    sections: list

    def to_dict(self):
        return asdict(self)


def decode_bill(bill_text: str, api_key: Optional[str] = None) -> DecodeResult:
    """
    Send bill text to Gemini and get back a structured decode.
    Raises ValueError if the model doesn't return valid JSON matching the schema.
    """
    client = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY"))

    response = call_gemini_with_retry(
        client,
        model=MODEL,
        contents=f"Decode this bill:\n\n{bill_text}",
        config=types.GenerateContentConfig(
            system_instruction=DECODE_SYSTEM_PROMPT,
            response_mime_type="application/json",
        ),
    )

    raw = response.text.strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Model did not return valid JSON: {e}\n\nRaw output:\n{raw}")

    return DecodeResult(
        title=data.get("title", ""),
        what_it_is=data.get("what_it_is", ""),
        who_it_affects=data.get("who_it_affects", ""),
        why_it_matters=data.get("why_it_matters", ""),
        key_dates=data.get("key_dates", []),
        what_you_can_do=data.get("what_you_can_do", []),
        sections=data.get("sections", []),
    )


if __name__ == "__main__":
    # Quick manual test — change the filename to try a different bill
    with open(os.path.join(os.path.dirname(__file__), "..", "data", "sample_bill.txt")) as f:
        text = f.read()

    result = decode_bill(text)
    print(json.dumps(result.to_dict(), indent=2))