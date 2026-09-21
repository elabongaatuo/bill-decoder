"""
Proof-of-concept: a REAL, live extraction of one bill's text from Kenya
Law, matched against Mzalendo Trust's Bill Tracker for stage/sponsor data.

HONESTY CHECK, upfront: this makes real HTTP requests to two live
websites. It has NOT been end-to-end tested — the environment this code
was written in has no network access to either domain, so this is a
careful, real attempt, not a verified one. Expect it may need a debugging
round together the first time you run it, the same way we worked through
the SSL issue earlier. Budget time for that; don't run this for the
first time the night before your demo.

Why it's written this way: rather than guessing at exact CSS class names
(which risks silently breaking the moment the site's markup differs even
slightly from a guess), this matches by LINK TEXT and FILE EXTENSION
patterns — more resilient, but still a best-effort approach given the
page structure wasn't inspected firsthand before writing this.

What it does:
  1. Fetches Kenya Law's bills listing, looks for a link whose visible
     text matches TARGET_TITLE.
  2. Follows that link, looks for a PDF link on the resulting page.
  3. Downloads the PDF and extracts its text (most Kenya Law bills have a
     real text layer, not scanned images — confirmed earlier on the
     Coroners Bill you uploaded).
  4. Separately searches Mzalendo's Bill Tracker for a bill matching the
     same title, and pulls whatever stage/sponsor info it can find.
  5. Writes bill text + matched metadata to data/<slug>_extracted.txt

Requires: pip install beautifulsoup4 pymupdf

Run from inside app/:
    python3 extract_one_bill.py
"""

import os
import re
import sys

import requests
from bs4 import BeautifulSoup
import fitz  # PyMuPDF

# Change this to try a different bill. Must match the link text on Kenya
# Law's listing closely enough — check the printed output if it's not found.
TARGET_TITLE = "The National Coroners Service Bill, 2026"

KENYALAW_BILLS_URL = "https://new.kenyalaw.org/bills/"
MZALENDO_SEARCH_URL = "https://mzalendo.com/search/"

HEADERS = {"User-Agent": "Mozilla/5.0 (BillBridge proof-of-concept extractor)"}


def find_bill_link_on_kenyalaw(target_title: str) -> str | None:
    resp = requests.get(KENYALAW_BILLS_URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    for link in soup.find_all("a"):
        text = link.get_text(strip=True)
        if text and target_title.lower() in text.lower():
            href = link.get("href")
            if href:
                if href.startswith("/"):
                    href = "https://new.kenyalaw.org" + href
                return href

    # Nothing matched — print what WAS found, to make debugging fast
    # rather than leaving you staring at a bare failure.
    print("No exact match. Bill-like links actually found on this page:")
    for link in soup.find_all("a"):
        text = link.get_text(strip=True)
        if text and re.search(r"Bill.*20\d\d", text):
            print(f"  - {text!r} -> {link.get('href')}")
    return None


def find_pdf_link_on_bill_page(bill_page_url: str) -> str | None:
    resp = requests.get(bill_page_url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Kenya Law renders bills through a JS-loaded PDF viewer — the real PDF
    # URL lives in a data-pdf="..." attribute (confirmed from a real fetched
    # page), not as a plain <a href="...pdf"> link. Check that first.
    pdf_holder = soup.find(attrs={"data-pdf": True})
    if pdf_holder:
        href = pdf_holder["data-pdf"]
        if href.startswith("/"):
            href = "https://new.kenyalaw.org" + href
        return href

    # Fallback: a plain anchor ending in .pdf, in case some pages use that
    # simpler pattern instead.
    for link in soup.find_all("a"):
        href = link.get("href", "")
        if href.lower().endswith(".pdf"):
            if href.startswith("/"):
                href = "https://new.kenyalaw.org" + href
            return href

    return None


# Boilerplate that appears on every Kenya Law page — used to trim navigation
# and footer text from the extracted content, since the site apparently
# renders full legal text directly in the page's HTML (confirmed on a
# similar Kenya Law page), not just as a downloadable PDF.
_NAV_START_MARKERS = ["Skip to document content", "Go to main menu"]
_CONTENT_START_MARKERS = ["A Bill for", "AN ACT of Parliament", "PART I", "PRELIMINARY"]
_FOOTER_MARKERS = ["Related documents", "Table of Contents", "Comments/Questions?"]


def extract_bill_text_from_html_page(bill_page_url: str) -> str | None:
    """
    Try pulling the bill's text directly from the page's own HTML, rather
    than assuming it must be a separate PDF. Trims obvious nav/footer
    boilerplate using landmark phrases rather than CSS classes we haven't
    inspected directly — resilient to markup, brittle to Kenya Law changing
    their standard section headings, which is an acceptable trade for a
    proof of concept.
    """
    resp = requests.get(bill_page_url, headers=HEADERS, timeout=20)
    resp.raise_for_status()

    # Debug dump: save the raw response so a failed extraction can actually
    # be inspected afterward, rather than just failing silently. Harmless
    # to leave in — it's cheap and overwritten each run.
    debug_path = os.path.join(os.path.dirname(__file__), "..", "data", "_last_fetch_debug.html")
    with open(debug_path, "w", encoding="utf-8") as f:
        f.write(resp.text)
    print(f"[debug] Raw response ({len(resp.text)} chars) saved to {debug_path}")

    soup = BeautifulSoup(resp.text, "html.parser")
    full_text = soup.get_text("\n", strip=True)

    start_idx = -1
    for marker in _CONTENT_START_MARKERS:
        idx = full_text.find(marker)
        if idx != -1 and (start_idx == -1 or idx < start_idx):
            start_idx = idx

    if start_idx == -1:
        return None  # couldn't find a recognizable start of the bill text

    trimmed = full_text[start_idx:]

    for marker in _FOOTER_MARKERS:
        idx = trimmed.find(marker)
        if idx != -1:
            trimmed = trimmed[:idx]

    return trimmed.strip()


def extract_pdf_text(pdf_url: str) -> str:
    resp = requests.get(pdf_url, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    doc = fitz.open(stream=resp.content, filetype="pdf")
    text_parts = [page.get_text() for page in doc]
    doc.close()
    return "\n".join(text_parts)


def find_mzalendo_match(target_title: str) -> dict:
    """Best-effort — returns {} rather than raising if no confident match
    is found, same graceful-degradation approach we used manually earlier
    for bills Mzalendo hadn't indexed yet."""
    try:
        resp = requests.get(
            MZALENDO_SEARCH_URL, params={"q": target_title}, headers=HEADERS, timeout=20
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        for link in soup.find_all("a", href=True):
            if "/legislative-trends/bills/" in link["href"]:
                tracker_url = link["href"]
                if tracker_url.startswith("/"):
                    tracker_url = "https://mzalendo.com" + tracker_url
                return _scrape_mzalendo_tracker_page(tracker_url)
    except requests.RequestException as e:
        print(f"[extract] Mzalendo search failed (continuing without it): {e}")

    return {}


def _scrape_mzalendo_tracker_page(url: str) -> dict:
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    text = BeautifulSoup(resp.text, "html.parser").get_text("\n", strip=True)

    stage_match = re.search(
        r"(First Reading|Second Reading|Third Reading|Committee[^\n]{0,40}|Presidential Assent)[^\n]{0,60}",
        text,
    )
    sponsor_match = re.search(r"Sponsor[:\s]+([A-Z][a-zA-Z .'-]+)", text)

    return {
        "mzalendo_url": url,
        "stage_guess": stage_match.group(0).strip() if stage_match else None,
        "sponsor_guess": sponsor_match.group(1).strip() if sponsor_match else None,
    }


def slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")


if __name__ == "__main__":
    print(f"Looking for '{TARGET_TITLE}' on Kenya Law...")
    bill_page = find_bill_link_on_kenyalaw(TARGET_TITLE)
    if not bill_page:
        print("\nCould not find a matching link. See candidates printed above —")
        print("adjust TARGET_TITLE to match one exactly, then rerun.")
        sys.exit(1)
    print(f"Found bill page: {bill_page}")

    print("Trying to extract bill text directly from the page's HTML...")
    bill_text = extract_bill_text_from_html_page(bill_page)
    pdf_url = None

    if bill_text and len(bill_text) > 500:
        print(f"Extracted {len(bill_text)} characters directly from HTML — no PDF needed.")
    else:
        print("HTML extraction came back empty or too short. Falling back to PDF...")
        pdf_url = find_pdf_link_on_bill_page(bill_page)
        if not pdf_url:
            print("Could not find a PDF link either. You may need to open the page")
            print("in a browser and adjust the extraction markers manually.")
            sys.exit(1)
        print(f"Found PDF: {pdf_url}")
        print("Extracting text from the PDF...")
        bill_text = extract_pdf_text(pdf_url)
        print(f"Extracted {len(bill_text)} characters.")

    if len(bill_text) < 500:
        print("WARNING: that's a suspiciously small amount of text — this source")
        print("may need OCR or a different extraction approach entirely.")

    print("Searching Mzalendo for matching stage/sponsor data...")
    mzalendo_info = find_mzalendo_match(TARGET_TITLE)
    if mzalendo_info:
        print(f"Matched: {mzalendo_info}")
    else:
        print("No confident Mzalendo match found — continuing without it.")

    out_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{slugify(TARGET_TITLE)}_extracted.txt")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"SOURCE: {bill_page}\n")
        f.write(f"PDF: {pdf_url or '(extracted directly from HTML, no PDF used)'}\n")
        if mzalendo_info:
            f.write(f"MZALENDO MATCH: {mzalendo_info}\n")
        f.write("\n---\n\n")
        f.write(bill_text)

    print(f"\nDone. Written to {out_path}")