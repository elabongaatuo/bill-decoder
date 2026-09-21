"""
Thin wrapper around the Africa's Talking SMS SDK.

Sandbox notes (confirmed from their docs):
  - In sandbox mode, messages are NOT delivered to real phones. You'll see
    them logged in the AT dashboard under Bulk SMS -> Outbox with a status.
    That's fine for demo purposes — show the outbox as proof of send.
  - Sandbox username is always the literal string "sandbox". Your API key
    still comes from your sandbox app dashboard.
  - GSM charset messages get ~160 chars per segment; anything with characters
    outside GSM 03.38 (many Swahili accented chars are fine, but check yours)
    can drop to ~70 chars per segment. Test your actual Swahili strings early.

Set these env vars before running:
  AT_USERNAME=sandbox
  AT_API_KEY=<your sandbox api key>
"""

import json
import os
import subprocess
import textwrap
from typing import Optional

import ssl_patch  # noqa: F401 — must be imported before africastalking/requests; see ssl_patch.py

import africastalking

_initialized = False


def _ensure_init():
    global _initialized
    if not _initialized:
        africastalking.initialize(
            username=os.environ.get("AT_USERNAME", "sandbox"),
            api_key=os.environ["AT_API_KEY"],
        )
        _initialized = True


def _send_sms_via_curl(phone_number: str, message: str) -> dict:
    """
    Fallback path: sends the SMS by shelling out to curl.exe instead of
    going through requests/urllib3's own TLS stack.

    This exists because of a machine-specific TLS handshake failure
    (SSL: WRONG_VERSION_NUMBER) against api.sandbox.africastalking.com that
    affects Python's OpenSSL-based client here, but not curl or a browser
    (which use Windows' own TLS stack). Multiple targeted fixes to Python's
    SSL configuration did not resolve it, so this sidesteps the problem
    entirely by using the tool that's already proven to work.
    """
    api_key = os.environ["AT_API_KEY"]
    username = os.environ.get("AT_USERNAME", "sandbox")
    url = "https://api.sandbox.africastalking.com/version1/messaging"

    result = subprocess.run(
        [
            "curl.exe", "-s", "-X", "POST", url,
            "-H", f"apiKey: {api_key}",
            "-H", "Content-Type: application/x-www-form-urlencoded",
            "-H", "Accept: application/json",
            "--data-urlencode", f"username={username}",
            "--data-urlencode", f"to={phone_number}",
            "--data-urlencode", f"message={message}",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )

    if result.returncode != 0:
        raise RuntimeError(f"curl fallback failed (exit {result.returncode}): {result.stderr}")

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"raw_response": result.stdout}


def send_sms(phone_number: str, message: str) -> dict:
    """Send a single SMS. Returns the AT API response dict.

    Tries the normal africastalking SDK first; falls back to a curl-based
    send if that fails with an SSL error (see _send_sms_via_curl above for
    why this fallback exists).
    """
    _ensure_init()
    try:
        sms = africastalking.SMS
        return sms.send(message, [phone_number])
    except Exception as e:
        if "SSL" in type(e).__name__ or "SSL" in str(e):
            print(f"[sms_client] SDK send failed with an SSL error, falling back to curl: {e}")
            return _send_sms_via_curl(phone_number, message)
        raise


def send_bill_summary_sms(phone_number: str, decoded: dict, language: str = "en") -> list:
    """
    Send a bill summary as one or more SMS segments. Long summaries get split
    into labeled parts (1/3, 2/3, ...) since a full decode won't fit in one
    SMS segment.
    """
    labels = {
        "en": {"what": "WHAT", "who": "WHO", "why": "WHY", "dates": "DATES", "do": "DO"},
        "sw": {"what": "NINI", "who": "NANI", "why": "KWANINI", "dates": "TAREHE", "do": "FANYA"},
    }[language if language in ("en", "sw") else "en"]

    parts = [
        f"{decoded['title']}",
        f"{labels['what']}: {decoded['what_it_is']}",
        f"{labels['who']}: {decoded['who_it_affects']}",
        f"{labels['why']}: {decoded['why_it_matters']}",
    ]

    if decoded.get("key_dates"):
        dates_str = "; ".join(f"{d['label']}: {d['detail']}" for d in decoded["key_dates"])
        parts.append(f"{labels['dates']}: {dates_str}")

    if decoded.get("what_you_can_do"):
        actions_str = "; ".join(f"{a['action']} ({a['where']})" for a in decoded["what_you_can_do"])
        parts.append(f"{labels['do']}: {actions_str}")

    full_text = " | ".join(parts)

    # Split into ~150-char chunks (leaving headroom for "(n/m)" labels),
    # respecting word boundaries.
    max_len = 145
    chunks = textwrap.wrap(full_text, max_len, break_long_words=False)
    total = len(chunks)

    responses = []
    for i, chunk in enumerate(chunks, start=1):
        labeled = f"({i}/{total}) {chunk}" if total > 1 else chunk
        responses.append(send_sms(phone_number, labeled))

    return responses


def send_notification_sms(phone_number: str, bill_title: str, stage: str, language: str = "en") -> dict:
    """Short ping when a subscribed bill changes stage."""
    if language == "sw":
        message = f"SASISHO: '{bill_title}' sasa iko katika hatua: {stage}. Tuma HELP kwa maelezo zaidi."
    else:
        message = f"UPDATE: '{bill_title}' has moved to stage: {stage}. Text HELP for more info."
    return send_sms(phone_number, message)


def send_petition_confirmation_sms(phone_number: str, bill_title: str, tally: int, language: str = "en") -> dict:
    if language == "sw":
        message = f"Asante! Nafasi yako kuhusu '{bill_title}' imesajiliwa. Jumla ya watu {tally} wamejiandikisha."
    else:
        message = f"Thanks! Your position on '{bill_title}' has been recorded. {tally} people have registered via this system so far."
    return send_sms(phone_number, message)