"""
Diagnostic: checks exactly what's in the database right now for each bill's
decoded_sw field, bypassing the web app / USSD entirely.

Run from inside app/:
    python3 check_swahili_data.py
"""

from models import Bill, SessionLocal

db = SessionLocal()
bills = db.query(Bill).order_by(Bill.created_at.desc()).all()

if not bills:
    print("No bills in the database at all. Run seed_bills.py first.")
else:
    for b in bills:
        print(f"\n--- {b.reference_code} — {b.title} ---")
        if b.decoded_sw is None:
            print("decoded_sw: None (no Swahili saved for this bill)")
        else:
            title_sw = b.decoded_sw.get("title", "")
            print(f"decoded_sw IS set. Its 'title' field reads: {title_sw!r}")
            # A rough check: does it actually look like Swahili, or English
            # that got saved into the sw slot by mistake?
            looks_swahili = any(w in title_sw.lower() for w in ["mswada", "sheria", "ya", "wa"])
            print(f"Looks like real Swahili text: {looks_swahili}")

db.close()