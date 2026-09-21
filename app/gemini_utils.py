"""
Shared helper: retry a Gemini call with exponential backoff on transient
server errors (503 UNAVAILABLE and similar). Demand spikes on Google's side
are common and temporary — this keeps a single busy moment from failing
outright, which matters most during a live demo.
"""

import time

from google.genai import errors as genai_errors


def call_gemini_with_retry(client, retries: int = 3, delay: float = 3.0, **kwargs):
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            return client.models.generate_content(**kwargs)
        except genai_errors.ServerError as e:
            last_error = e
            if attempt < retries:
                wait = delay * attempt
                print(f"[gemini] server busy (attempt {attempt}/{retries}), retrying in {wait:.0f}s...")
                time.sleep(wait)
    raise last_error