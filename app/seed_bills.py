"""
Load bills into the database directly from already-decoded JSON files,
with NO Gemini calls. Use this while testing USSD/SMS so you're not
re-decoding (and re-risking a 503) every time you want data in the app.

Run from inside app/:
    python3 seed_bills.py
"""

import json
import os

from models import Bill, init_db, SessionLocal

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

# (reference_code, title, raw_text_file, decoded_en_file, decoded_sw_file_or_None, tags)
BILLS_TO_SEED = [
    (
        "CORONERS-2026",
        "National Coroners Service Bill, 2026",
        "coroners_bill_2026.txt",
        "coroners_bill_2026_decoded.json",
        "coroners_bill_2026_decoded_sw.json",  # Swahili not yet generated — add "coroners_bill_2026_sw.json" once you have it
        "health,justice,national",
    ),
    (
        "AI-BILL-2026",
        "Artificial Intelligence Bill, 2026",
        "ai_bill_2026.txt",
        "ai_bill_2026_decoded.json",
        "ai_bill_2026_decoded_sw.json",
        "technology,senate,national",
    ),
    # Public Participation Bill: add its own entry here once decoder.py has
    # been run on public_participation_bill_2025.txt and you've saved the
    # output as public_participation_bill_2025_decoded.json, same pattern
    # as the two above.
]


def seed():
    init_db()
    db = SessionLocal()

    for ref_code, title, raw_file, decoded_en_file, decoded_sw_file, tags in BILLS_TO_SEED:
        existing = db.query(Bill).filter(Bill.reference_code == ref_code).first()
        if existing:
            print(f"Skipping {ref_code} — already in database (id={existing.id})")
            continue

        with open(os.path.join(DATA_DIR, raw_file), encoding="utf-8") as f:
            raw_text = f.read()

        with open(os.path.join(DATA_DIR, decoded_en_file), encoding="utf-8") as f:
            decoded_en = json.load(f)

        decoded_sw = None
        if decoded_sw_file:
            sw_path = os.path.join(DATA_DIR, decoded_sw_file)
            if os.path.exists(sw_path):
                with open(sw_path, encoding="utf-8") as f:
                    decoded_sw = json.load(f)

        bill = Bill(
            reference_code=ref_code,
            title=title,
            raw_text=raw_text,
            decoded_en=decoded_en,
            decoded_sw=decoded_sw,
            tags=tags,
            stage="introduced",
        )
        db.add(bill)
        db.commit()
        db.refresh(bill)
        print(f"Seeded {ref_code} — id={bill.id}, title='{bill.title}'"
              + (" (no Swahili yet)" if decoded_sw is None else ""))

    db.close()


if __name__ == "__main__":
    seed()