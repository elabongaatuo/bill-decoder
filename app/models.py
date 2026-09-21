"""
SQLite schema via SQLAlchemy. Deliberately simple for a 4-day build —
one file, no migrations framework. If this needs to grow later, swap the
sqlite:// URL for a Postgres one and it mostly just works.
"""

from datetime import datetime

from sqlalchemy import (
    create_engine, Column, Integer, String, Text, DateTime, ForeignKey, JSON
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

Base = declarative_base()


class Bill(Base):
    __tablename__ = "bills"

    id = Column(Integer, primary_key=True)
    reference_code = Column(String, unique=True, nullable=False)  # e.g. "HEALTH-AMEND-2026"
    title = Column(String, nullable=False)
    source_url = Column(String)  # link to the original parliament PDF/page
    raw_text = Column(Text)  # OCR'd or plain text used for decoding

    # Lifecycle stage: track where the bill is in the process.
    # Kept as a free string rather than an enum for now, so we can adjust
    # stage names without a migration, e.g.:
    # "introduced" -> "public_participation_open" -> "committee_review"
    # -> "second_reading" -> "assented" -> "in_force"
    stage = Column(String, default="introduced")
    stage_updated_at = Column(DateTime, default=datetime.utcnow)

    # Comment period deadline, if applicable to current stage
    comment_deadline = Column(DateTime, nullable=True)

    decoded_en = Column(JSON)  # cached English decode output
    decoded_sw = Column(JSON)  # cached Swahili decode output

    tags = Column(String)  # comma-separated, e.g. "health,county,licensing"

    created_at = Column(DateTime, default=datetime.utcnow)

    subscriptions = relationship("Subscription", back_populates="bill")
    petition_signatures = relationship("PetitionSignature", back_populates="bill")
    comments = relationship("Comment", back_populates="bill")


class Subscription(Base):
    """A phone number subscribed to updates on a bill (or a tag)."""
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True)
    phone_number = Column(String, nullable=False, index=True)
    bill_id = Column(Integer, ForeignKey("bills.id"), nullable=True)  # null if tag-based
    tag = Column(String, nullable=True)  # e.g. "health" — subscribe to a topic, not one bill
    language_pref = Column(String, default="en")  # "en" or "sw"
    created_at = Column(DateTime, default=datetime.utcnow)

    bill = relationship("Bill", back_populates="subscriptions")


class PetitionSignature(Base):
    """Lightweight tally: a phone number recorded a position on a bill.

    Deliberately NOT a formal/official petition mechanism — just a count
    ("N people have registered support via this system") for demo purposes.
    """
    __tablename__ = "petition_signatures"

    id = Column(Integer, primary_key=True)
    phone_number = Column(String, nullable=False, index=True)
    bill_id = Column(Integer, ForeignKey("bills.id"), nullable=False)
    position = Column(String, default="support")  # "support" or "oppose"
    created_at = Column(DateTime, default=datetime.utcnow)

    bill = relationship("Bill", back_populates="petition_signatures")


class SmsQuery(Base):
    """Log of free-text questions asked via SMS, for debugging + demo evidence."""
    __tablename__ = "sms_queries"

    id = Column(Integer, primary_key=True)
    phone_number = Column(String, nullable=False)
    bill_id = Column(Integer, ForeignKey("bills.id"), nullable=True)
    question_text = Column(Text, nullable=False)
    answer_text = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class Comment(Base):
    """Anonymous discussion comment on a bill — no sign-in required.

    Deliberately minimal moderation for this build: a length cap and a
    small denylist check (see main.py). Real moderation tooling is named
    explicitly as future work, not silently skipped.
    """
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True)
    bill_id = Column(Integer, ForeignKey("bills.id"), nullable=False)
    nickname = Column(String, default="Anonymous")  # user-chosen, not an identity
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    bill = relationship("Bill", back_populates="comments")


# --- engine / session setup ---

DB_URL = "sqlite:///./bill_decoder.db"
engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_URL}")