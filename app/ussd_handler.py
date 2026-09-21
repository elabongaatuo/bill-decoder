"""
USSD menu logic.

How Africa's Talking USSD works (confirmed from their docs):
  - You register a callback URL. Every user interaction (dialing in, or
    entering more text at any menu level) triggers a fresh HTTP POST to that
    URL with the FULL text of everything the user has entered so far in the
    session, separated by "*".
  - You must respond with plain text within ~10 seconds.
  - Prefix your response with "CON " to keep the session open (show another
    menu) or "END " to close it (final message).
  - Sessions time out after ~3 minutes of inactivity — keep menus shallow
    and fast, don't make users hunt through deep nested menus.

This handler is intentionally stateless: it parses the FULL input string each
time to figure out what menu level the user is on, rather than storing session
state server-side. Simpler to reason about and matches how AT's model works.

Two ways to reach a specific bill, both converging on the same per-bill
action menu:
  "1"            -> browse recent bills
  "1*<idx>"      -> chose a bill from that list
  "1*<idx>*<action>"

  "2"            -> prompted for a topic keyword
  "2*<topic>"    -> bills matching that topic (matched against Bill.tags)
  "2*<topic>*<idx>"
  "2*<topic>*<idx>*<action>"

Per-bill actions:
  1 = get summary in English (SMS)
  2 = get summary in Kiswahili (SMS) — falls back to English with a note if
      no Swahili translation has been generated for that bill yet
  3 = subscribe to updates
  4 = support this bill
  5 = oppose this bill
"""

from sqlalchemy.orm import Session

from models import Bill

RECENT_LIMIT = 5


def handle_ussd_request(session_id: str, phone_number: str, text: str, db: Session) -> str:
    parts = text.split("*") if text else []

    # Global "0 = back" handling: every "0. Back" shown on screen means
    # "re-render the parent menu", not a numbered choice — so we intercept
    # it here, before any level-specific logic, and recurse into whatever
    # input would have produced that parent screen. This also correctly
    # stops "0" from ever being misread as a bill index or a literal topic
    # search term.
    if parts and parts[-1] == "0":
        parent_text = _parent_text(parts)
        return handle_ussd_request(session_id, phone_number, parent_text, db)

    # Level 0: just dialed in -> main menu
    if text == "":
        return (
            "CON Welcome to Bill Bridge\n"
            "1. Browse bills\n"
            "2. Search by topic\n"
            "3. My subscriptions\n"
            "4. Help"
        )

    # Level 1: main menu choice
    if len(parts) == 1:
        choice = parts[0]
        if choice == "1":
            return _list_bills_menu(db)
        elif choice == "2":
            return (
                "CON Reply with a topic keyword (e.g. health, technology, national):\n"
                "0. Back"
            )
        elif choice == "3":
            return _list_subscriptions_menu(phone_number, db)
        elif choice == "4":
            return (
                "END Bill Bridge decodes Kenyan parliamentary bills into "
                "plain language, in English or Kiswahili. Dial in again "
                "any time to browse, subscribe, or vote."
            )
        else:
            return "END Invalid choice. Please dial in again."

    # --- Browse path: "1" ---
    if parts[0] == "1":
        if len(parts) == 2:
            bill = _get_bill_by_menu_index(db, parts[1])
            if not bill:
                return "END Bill not found. Please dial in again."
            return _bill_action_menu(bill)

        if len(parts) == 3:
            bill = _get_bill_by_menu_index(db, parts[1])
            if not bill:
                return "END Bill not found."
            return _bill_action_response(bill, parts[2])

    # --- Topic search path: "2" ---
    if parts[0] == "2":
        if len(parts) == 2:
            topic = parts[1].strip()
            return _list_bills_by_topic_menu(db, topic)

        if len(parts) == 3:
            topic = parts[1].strip()
            bill = _get_bill_by_topic_and_index(db, topic, parts[2])
            if not bill:
                return "END Bill not found. Please search again."
            return _bill_action_menu(bill)

        if len(parts) == 4:
            topic = parts[1].strip()
            bill = _get_bill_by_topic_and_index(db, topic, parts[2])
            if not bill:
                return "END Bill not found."
            return _bill_action_response(bill, parts[3])

    return "END Session error. Please dial in again."


def _parent_text(parts: list[str]) -> str:
    """
    Given the path segments up to and including the trailing "0" that
    triggered a back-navigation, return the input text that would render
    the correct parent menu.
    """
    # "0" pressed at the very top level — nowhere to go but the main menu.
    if len(parts) == 1:
        return ""

    if parts[0] == "1":
        if len(parts) == 2:   # "1*0" — was at bill list -> back to main menu
            return ""
        if len(parts) == 3:   # "1*<idx>*0" — was at bill action menu -> back to bill list
            return "1"

    if parts[0] == "2":
        if len(parts) == 2:   # "2*0" — was being asked for a topic -> back to main menu
            return ""
        if len(parts) == 3:   # "2*<topic>*0" — was at topic results -> back to topic prompt
            return "2"
        if len(parts) == 4:   # "2*<topic>*<idx>*0" — was at bill action menu -> back to topic results
            return f"2*{parts[1]}"

    # Fallback: if the shape is unexpected, safest is the main menu.
    return ""


def _bill_action_menu(bill: Bill) -> str:
    sw_note = "" if bill.decoded_sw else " (not yet available)"
    return (
        f"CON {bill.title}\n"
        "1. Get summary - English (SMS)\n"
        f"2. Get summary - Kiswahili (SMS){sw_note}\n"
        "3. Subscribe to updates\n"
        "4. Support this bill\n"
        "5. Oppose this bill\n"
        "0. Back"
    )


def _bill_action_response(bill: Bill, action: str) -> str:
    """
    The CON/END text shown to the user for a chosen action. The actual SMS
    send / DB write for that action happens as a side effect in main.py,
    which inspects this same `action` value after calling this handler.
    """
    if action == "1":
        return "END Summary sent via SMS (English). Check your messages shortly."
    elif action == "2":
        if bill.decoded_sw:
            return "END Muhtasari umetumwa kwa SMS (Kiswahili). Angalia ujumbe wako."
        else:
            return (
                "END Kiswahili is not yet available for this bill — "
                "sending the English summary instead. Check your messages shortly."
            )
    elif action == "3":
        return "END You are now subscribed to updates on this bill."
    elif action == "4":
        return "END Thank you. Your support has been recorded."
    elif action == "5":
        return "END Thank you. Your opposition has been recorded."
    else:
        return "END Invalid choice."


def _list_bills_menu(db: Session) -> str:
    bills = db.query(Bill).order_by(Bill.created_at.desc()).limit(RECENT_LIMIT).all()
    if not bills:
        return "END No bills available right now. Please check back later."

    lines = ["CON Recent bills:"]
    for i, bill in enumerate(bills, start=1):
        short_title = bill.title[:35] + ("..." if len(bill.title) > 35 else "")
        lines.append(f"{i}. {short_title}")
    lines.append("0. Back")
    return "\n".join(lines)


def _get_bill_by_menu_index(db: Session, index_str: str) -> Bill | None:
    try:
        index = int(index_str) - 1
    except ValueError:
        return None
    bills = db.query(Bill).order_by(Bill.created_at.desc()).limit(RECENT_LIMIT).all()
    if 0 <= index < len(bills):
        return bills[index]
    return None


def _matching_bills_for_topic(db: Session, topic: str) -> list[Bill]:
    """
    Simple case-insensitive substring match against the comma-separated
    Bill.tags field. Fine at this scale (a handful of bills); would need a
    real search index if the bill count grew much beyond a demo dataset.
    """
    if not topic:
        return []
    topic_lower = topic.lower()
    bills = db.query(Bill).order_by(Bill.created_at.desc()).all()
    return [b for b in bills if b.tags and topic_lower in b.tags.lower()][:RECENT_LIMIT]


def _list_bills_by_topic_menu(db: Session, topic: str) -> str:
    matches = _matching_bills_for_topic(db, topic)
    if not matches:
        return f"END No bills found for topic '{topic}'. Please dial in again to try another topic."

    lines = [f"CON Bills tagged '{topic}':"]
    for i, bill in enumerate(matches, start=1):
        short_title = bill.title[:35] + ("..." if len(bill.title) > 35 else "")
        lines.append(f"{i}. {short_title}")
    lines.append("0. Back")
    return "\n".join(lines)


def _get_bill_by_topic_and_index(db: Session, topic: str, index_str: str) -> Bill | None:
    try:
        index = int(index_str) - 1
    except ValueError:
        return None
    matches = _matching_bills_for_topic(db, topic)
    if 0 <= index < len(matches):
        return matches[index]
    return None


def _list_subscriptions_menu(phone_number: str, db: Session) -> str:
    from models import Subscription

    subs = db.query(Subscription).filter(Subscription.phone_number == phone_number).all()
    if not subs:
        return "END You have no active subscriptions."

    lines = ["END Your subscriptions:"]
    for sub in subs:
        if sub.bill:
            lines.append(f"- {sub.bill.title[:30]}")
        elif sub.tag:
            lines.append(f"- Topic: {sub.tag}")
    return "\n".join(lines)