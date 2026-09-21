"""
Main FastAPI app. This is what you deploy and point Africa's Talking's
callback URLs at.

Endpoints:
  POST /ussd            <- Africa's Talking USSD callback
  POST /sms/incoming    <- Africa's Talking "incoming SMS" callback (questions)
  POST /admin/bills     <- add a bill (decode + translate + store)
  GET  /admin/bills     <- list stored bills
  POST /admin/bills/{id}/stage  <- move a bill to a new lifecycle stage (notifies subscribers)
  POST /subscribe       <- subscribe a phone number to a bill or tag (also reachable via USSD)
  POST /petition        <- record a support/oppose position on a bill

Run locally:
    uvicorn app.main:app --reload --port 8000

Then expose it publicly for AT's callbacks with something like ngrok:
    ngrok http 8000
and put the ngrok https URL + "/ussd" or "/sms/incoming" into your AT
sandbox dashboard callback fields.
"""

from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
load_dotenv()  # reads .env into environment variables before anything else runs

from fastapi import FastAPI, Depends, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from decoder import decode_bill
from translator import translate_decode
from models import Bill, Subscription, PetitionSignature, Comment, get_db, init_db
from ussd_handler import handle_ussd_request
from qa import handle_sms_question
from sms_client import send_bill_summary_sms, send_notification_sms, send_petition_confirmation_sms

app = FastAPI(title="Bill Bridge")

# Allow the local web app (opened from a file:// page or a dev server on a
# different port) to call this API. Wide open here because this is a local
# demo — tighten this before ever deploying somewhere public.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()


# --- USSD ---

@app.post("/ussd", response_class=PlainTextResponse)
def ussd_callback(
    sessionId: str = Form(...),
    phoneNumber: str = Form(...),
    text: str = Form(""),
    db: Session = Depends(get_db),
):
    response_text = handle_ussd_request(sessionId, phoneNumber, text, db)

    # Side effects (SMS sends, DB writes) happen here, after generating the
    # USSD response, since USSD replies must stay short/instant while an SMS
    # send is a separate, slower operation. Two ways to reach a bill+action:
    #   "1*<idx>*<action>"          — browse path
    #   "2*<topic>*<idx>*<action>"  — topic search path
    # Resolve to the actual Bill + action digit regardless of which path
    # was used, then apply the same side effect either way.
    parts = text.split("*") if text else []

    bill = None
    action = None

    if len(parts) == 3 and parts[0] == "1":
        from ussd_handler import _get_bill_by_menu_index
        bill = _get_bill_by_menu_index(db, parts[1])
        action = parts[2]
    elif len(parts) == 4 and parts[0] == "2":
        from ussd_handler import _get_bill_by_topic_and_index
        bill = _get_bill_by_topic_and_index(db, parts[1].strip(), parts[2])
        action = parts[3]

    if bill and action:
        if action == "1" and bill.decoded_en:
            # English summary
            send_bill_summary_sms(phoneNumber, bill.decoded_en, language="en")

        elif action == "2":
            # Kiswahili summary — falls back to English if not yet translated
            if bill.decoded_sw:
                send_bill_summary_sms(phoneNumber, bill.decoded_sw, language="sw")
            elif bill.decoded_en:
                send_bill_summary_sms(phoneNumber, bill.decoded_en, language="en")

        elif action == "3":
            # Subscribe
            existing = db.query(Subscription).filter(
                Subscription.phone_number == phoneNumber, Subscription.bill_id == bill.id
            ).first()
            if not existing:
                db.add(Subscription(phone_number=phoneNumber, bill_id=bill.id))
                db.commit()

        elif action in ("4", "5"):
            # Support / oppose
            position = "support" if action == "4" else "oppose"
            db.add(PetitionSignature(phone_number=phoneNumber, bill_id=bill.id, position=position))
            db.commit()
            tally = db.query(PetitionSignature).filter(
                PetitionSignature.bill_id == bill.id, PetitionSignature.position == position
            ).count()
            send_petition_confirmation_sms(phoneNumber, bill.title, tally)

    return response_text


# --- Incoming SMS (free-text questions) ---

@app.post("/sms/incoming", response_class=PlainTextResponse)
def sms_incoming(
    from_: str = Form(..., alias="from"),
    text: str = Form(...),
    db: Session = Depends(get_db),
):
    answer = handle_sms_question(from_, text, db)
    send_bill_summary_sms  # (import kept alive; actual send below)
    from sms_client import send_sms
    send_sms(from_, answer)
    return "OK"  # AT doesn't require a specific body for incoming-SMS acks


# --- Admin: manage bills ---

class BillIn(BaseModel):
    reference_code: str
    title: str
    source_url: Optional[str] = None
    raw_text: str
    tags: Optional[str] = None
    stage: str = "introduced"
    comment_deadline: Optional[datetime] = None


@app.post("/admin/bills")
def create_bill(bill_in: BillIn, db: Session = Depends(get_db)):
    decoded_en = decode_bill(bill_in.raw_text).to_dict()
    decoded_sw = translate_decode(decoded_en)

    bill = Bill(
        reference_code=bill_in.reference_code,
        title=bill_in.title,
        source_url=bill_in.source_url,
        raw_text=bill_in.raw_text,
        tags=bill_in.tags,
        stage=bill_in.stage,
        comment_deadline=bill_in.comment_deadline,
        decoded_en=decoded_en,
        decoded_sw=decoded_sw,
    )
    db.add(bill)
    db.commit()
    db.refresh(bill)
    return {"id": bill.id, "title": bill.title, "decoded_en": decoded_en}


@app.get("/admin/bills")
def list_bills(db: Session = Depends(get_db)):
    bills = db.query(Bill).order_by(Bill.created_at.desc()).all()
    return [{"id": b.id, "title": b.title, "stage": b.stage, "tags": b.tags} for b in bills]


# --- Public web app endpoints: bill detail, petition tallies, comments ---
# These are what the no-signup web app (web/index.html) actually calls.

@app.get("/bills")
def list_bills_public(db: Session = Depends(get_db)):
    """Same as /admin/bills, under a plainer path for the web app."""
    bills = db.query(Bill).order_by(Bill.created_at.desc()).all()
    return [{"id": b.id, "title": b.title, "stage": b.stage, "tags": b.tags} for b in bills]


@app.get("/bills/{bill_id}")
def get_bill_detail(bill_id: int, db: Session = Depends(get_db)):
    bill = db.query(Bill).filter(Bill.id == bill_id).first()
    if not bill:
        raise HTTPException(404, "Bill not found")

    support_count = db.query(PetitionSignature).filter(
        PetitionSignature.bill_id == bill_id, PetitionSignature.position == "support"
    ).count()
    oppose_count = db.query(PetitionSignature).filter(
        PetitionSignature.bill_id == bill_id, PetitionSignature.position == "oppose"
    ).count()

    return {
        "id": bill.id,
        "title": bill.title,
        "stage": bill.stage,
        "tags": bill.tags,
        "decoded_en": bill.decoded_en,
        "decoded_sw": bill.decoded_sw,
        "support_count": support_count,
        "oppose_count": oppose_count,
    }


# A short, fixed denylist as a minimal first line of moderation — catches
# the most obvious abuse without pretending to be a real moderation system.
# Real moderation tooling (reporting, rate limiting, a human review queue)
# is named as future work, not silently skipped — see the README.
_COMMENT_DENYLIST = ["<script", "javascript:"]
_MAX_COMMENT_LENGTH = 1000


class CommentIn(BaseModel):
    nickname: Optional[str] = "Anonymous"
    body: str


@app.get("/bills/{bill_id}/comments")
def list_comments(bill_id: int, db: Session = Depends(get_db)):
    comments = db.query(Comment).filter(Comment.bill_id == bill_id).order_by(Comment.created_at.asc()).all()
    return [
        {"id": c.id, "nickname": c.nickname or "Anonymous", "body": c.body, "created_at": c.created_at.isoformat()}
        for c in comments
    ]


@app.post("/bills/{bill_id}/comments")
def create_comment(bill_id: int, comment_in: CommentIn, db: Session = Depends(get_db)):
    bill = db.query(Bill).filter(Bill.id == bill_id).first()
    if not bill:
        raise HTTPException(404, "Bill not found")

    body = comment_in.body.strip()
    if not body:
        raise HTTPException(400, "Comment cannot be empty")
    if len(body) > _MAX_COMMENT_LENGTH:
        raise HTTPException(400, f"Comment too long (max {_MAX_COMMENT_LENGTH} characters)")
    if any(bad in body.lower() for bad in _COMMENT_DENYLIST):
        raise HTTPException(400, "Comment rejected by content filter")

    nickname = (comment_in.nickname or "Anonymous").strip()[:50] or "Anonymous"

    comment = Comment(bill_id=bill_id, nickname=nickname, body=body)
    db.add(comment)
    db.commit()
    db.refresh(comment)

    return {"id": comment.id, "nickname": comment.nickname, "body": comment.body, "created_at": comment.created_at.isoformat()}


class VoteIn(BaseModel):
    position: str  # "support" or "oppose"


@app.post("/bills/{bill_id}/vote")
def vote_web(bill_id: int, vote_in: VoteIn, db: Session = Depends(get_db)):
    """
    Anonymous web-based support/oppose vote — no phone number, no SMS
    confirmation. This is deliberately a simple tally, same honesty
    boundary as the USSD/SMS petition path: it records a position, it is
    not a formal or legally binding petition mechanism.
    """
    if vote_in.position not in ("support", "oppose"):
        raise HTTPException(400, "position must be 'support' or 'oppose'")

    bill = db.query(Bill).filter(Bill.id == bill_id).first()
    if not bill:
        raise HTTPException(404, "Bill not found")

    db.add(PetitionSignature(phone_number="web-anonymous", bill_id=bill_id, position=vote_in.position))
    db.commit()

    support_count = db.query(PetitionSignature).filter(
        PetitionSignature.bill_id == bill_id, PetitionSignature.position == "support"
    ).count()
    oppose_count = db.query(PetitionSignature).filter(
        PetitionSignature.bill_id == bill_id, PetitionSignature.position == "oppose"
    ).count()

    return {"support_count": support_count, "oppose_count": oppose_count}


class StageIn(BaseModel):
    stage: str


@app.post("/admin/bills/{bill_id}/stage")
def update_stage(bill_id: int, stage_in: StageIn, db: Session = Depends(get_db)):
    bill = db.query(Bill).filter(Bill.id == bill_id).first()
    if not bill:
        raise HTTPException(404, "Bill not found")

    bill.stage = stage_in.stage
    bill.stage_updated_at = datetime.utcnow()
    db.commit()

    # Notify all subscribers
    subs = db.query(Subscription).filter(Subscription.bill_id == bill_id).all()
    for sub in subs:
        send_notification_sms(sub.phone_number, bill.title, bill.stage, language=sub.language_pref)

    return {"id": bill.id, "stage": bill.stage, "notified": len(subs)}


# --- Subscribe / petition (also reachable via web, not just USSD) ---

class SubscribeIn(BaseModel):
    phone_number: str
    bill_id: Optional[int] = None
    tag: Optional[str] = None
    language_pref: str = "en"


@app.post("/subscribe")
def subscribe(sub_in: SubscribeIn, db: Session = Depends(get_db)):
    if not sub_in.bill_id and not sub_in.tag:
        raise HTTPException(400, "Must provide bill_id or tag")

    sub = Subscription(**sub_in.dict())
    db.add(sub)
    db.commit()
    return {"status": "subscribed"}


class PetitionIn(BaseModel):
    phone_number: str
    bill_id: int
    position: str = "support"


@app.post("/petition")
def petition(pet_in: PetitionIn, db: Session = Depends(get_db)):
    bill = db.query(Bill).filter(Bill.id == pet_in.bill_id).first()
    if not bill:
        raise HTTPException(404, "Bill not found")

    db.add(PetitionSignature(**pet_in.dict()))
    db.commit()

    tally = db.query(PetitionSignature).filter(
        PetitionSignature.bill_id == pet_in.bill_id, PetitionSignature.position == pet_in.position
    ).count()

    send_petition_confirmation_sms(pet_in.phone_number, bill.title, tally)
    return {"status": "recorded", "tally": tally}