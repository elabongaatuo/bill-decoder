"""
Translate an already-decoded bill JSON to Swahili, without re-running decode.
Uses exactly one Gemini call.

Usage:
    python translate_only.py path/to/decoded.json
"""

import json
import sys

from translator import translate_decode

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python translate_only.py data/coroners_bill_2026_decoded.json")
        sys.exit(1)

    with open(sys.argv[1], encoding="utf-8") as f:
        decoded = json.load(f)

    swahili = translate_decode(decoded)
    print(json.dumps(swahili, indent=2, ensure_ascii=False))