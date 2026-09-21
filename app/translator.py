"""
Second-pass translation: takes an already-decoded (English, plain-language)
bill summary and produces a Swahili version. Uses Gemini 2.5 Flash.

Run standalone for a quick test:
    python app/translator.py
"""

import json
import os
from typing import Optional

from dotenv import load_dotenv
load_dotenv()  # so GEMINI_API_KEY is available even when this file is run directly

from google import genai
from google.genai import types

from gemini_utils import call_gemini_with_retry

MODEL = "gemini-3.1-flash-lite"

TRANSLATE_SYSTEM_PROMPT = """You translate plain-language civic summaries from \
English to Swahili (Kenyan standard Swahili, not Tanzanian variants) for an SMS \
and USSD audience. Keep sentences short and use everyday vocabulary a person \
with basic education would understand — avoid overly formal or literary \
Swahili. Preserve all factual content exactly; do not add or drop information.

Terminology note: "coroner" / "coroners service" translates to "Korona" / \
"Wakorona" / "Huduma ya Wakorona" — this is the established Swahili legal \
term (used in Swahili-language legal and news coverage of coroner's courts), \
not a mistranslation. However, because "Korona" can otherwise be misread as \
referring to the coronavirus/COVID-19, the VERY FIRST time this term appears \
in the "title" field, add a short parenthetical clarifier immediately after \
it, e.g. "Wakorona (wanaochunguza visababisho vya kifo)" — since a citizen \
may see the bare title on its own in a USSD menu, without the surrounding \
sentence context that would otherwise disambiguate it. Subsequent uses in \
other fields do not need the parenthetical, since they appear alongside \
death/investigation-related words that already make the meaning clear.

You will receive a JSON object with the same schema as the English decode \
output. Return ONLY a JSON object with the same keys and structure, but with \
every text value translated to Swahili. Do not translate the "source_ref" \
values (e.g. "Section 14(3)") — keep those as-is since they refer to the \
official document."""


def translate_decode(decoded: dict, api_key: Optional[str] = None) -> dict:
    client = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY"))

    response = call_gemini_with_retry(
        client,
        model=MODEL,
        contents=json.dumps(decoded),
        config=types.GenerateContentConfig(
            system_instruction=TRANSLATE_SYSTEM_PROMPT,
            response_mime_type="application/json",
        ),
    )

    return json.loads(response.text.strip())


if __name__ == "__main__":
    from decoder import decode_bill

    with open(os.path.join(os.path.dirname(__file__), "..", "data", "sample_bill.txt")) as f:
        text = f.read()

    en = decode_bill(text).to_dict()
    sw = translate_decode(en)

    print("--- ENGLISH ---")
    print(json.dumps(en, indent=2))
    print("\n--- SWAHILI ---")
    print(json.dumps(sw, indent=2))