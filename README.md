# Bill Bridge

Decodes Kenyan parliamentary bills into plain language, in English or
Kiswahili, and makes them reachable over USSD, SMS, and a no-signup web
app. Built as a hackathon proof of concept for the OSF "Information You
Can Trust" challenge (Transparency & Accountability track).

## What actually works right now

- **Decode pipeline** (`decoder.py`): any bill's text turns into a
  structured plain-language summary (what it is, who it affects, why it
  matters, key dates, what you can do), and every claim cites back to a
  specific section of the source.
- **Translation** (`translator.py`): English to Kiswahili. The actual
  bill wording (`official_text`) stays untranslated on purpose, for
  source fidelity, while explanations get translated for accessibility.
- **USSD** (`ussd_handler.py` + `main.py`): browse bills, **search by
  topic** (`health`, `technology`, `national`, and so on, matched
  against each bill's tags), get a summary by SMS in English or
  Kiswahili, subscribe to updates, support or oppose a bill. Tested live
  against Africa's Talking's sandbox. The topic search exists so someone
  only sees bills tagged to what they actually care about, instead of
  scrolling through everything Parliament happens to be doing that week.
  It's USSD-only right now. Extending it to the web app's bill list is a
  small, near-term addition (see Roadmap).
- **SMS** (`sms_client.py`): summaries, notifications, petition
  confirmations, and free-text question-answering (`qa.py`). Ask a
  question about a bill, get an answer sourced from its decoded content.
- **Web app** (`web/index.html`): browse bills, read the full decode
  with expandable "show me the source" citations, vote support or
  oppose, post anonymous comments. No sign-in required.
- **Live extraction proof of concept** (`extract_one_bill.py`): a real,
  working script that finds a bill on Kenya Law's live site, downloads
  its PDF, and extracts the text. See "Data sourcing" below for what
  this covers and what it doesn't.

## Architecture, in one paragraph

Kenya Law, and, where available, Mzalendo Trust's Bill Tracker for
stage and sponsor data, feed a shared SQLite database. The
decode/translate pipeline reads bill text and writes structured output
back into that same database. This happens once, ahead of time, not
live during a USSD session. USSD/SMS and the web app are independent
front doors that both read from that one database, so a citizen dialing
in gets an instant response instead of waiting on a live AI call. The
one exception is SMS question-answering, which does call the model
live, since the question isn't known in advance.

## Prerequisites

- Python 3.11+ (developed and tested on 3.13)
- A free Gemini API key: https://aistudio.google.com/apikey (no card needed;
  free tier is roughly 1,500 requests/day)
- A free Africa's Talking sandbox account: https://account.africastalking.com/apps/sandbox
- [ngrok](https://ngrok.com/download) (or similar), to expose your local
  server for Africa's Talking's callbacks
- On Windows: no Visual Studio / C++ build tools needed — `pymupdf` in
  `requirements.txt` is left unpinned specifically so pip grabs a version with
  a prebuilt wheel rather than trying to compile from source

## Setup

```bash
git clone <this repo>
cd bill-decoder
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and fill in your real keys:

```
GEMINI_API_KEY=your_key_here
AT_USERNAME=sandbox
AT_API_KEY=your_sandbox_key_here
```

`.env` is already in `.gitignore` — never commit it, never paste a key into
any `.py` file directly.

## Running it

**1. Start the server** (from `app/`):
```bash
uvicorn main:app --reload --port 8000
```

**2. Expose it publicly** (in a second terminal):
```bash
ngrok http 8000
```
Copy the `https://....ngrok-free.dev` (or `.app`) URL it prints — you'll need
it in step 3, and **every time ngrok restarts, this URL changes**, so update
step 3 again if you ever stop and restart it.

**3. Point Africa's Talking at it.** In your sandbox dashboard's USSD channel
settings, set the callback URL to:
```
https://your-ngrok-url/ussd
```
Under SMS settings, set the incoming-SMS callback to:
```
https://your-ngrok-url/sms/incoming
```

**4. Load bills into the database.** Bills are decoded and seeded manually for
this proof of concept (see "Data sourcing" below for why). From `app/`:
```bash
python3 seed_bills.py
```
This reads pre-decoded JSON files already committed under `data/` and loads
them into a fresh `bill_decoder.db`. To add a new bill: run `decoder.py`
(and, if wanted, `translator.py`) against its raw text, save the JSON output
under `data/`, add an entry to `BILLS_TO_SEED` in `seed_bills.py`, and rerun
it — or use `update_bill_swahili.py <reference_code> <path>` to patch a
single bill's translation in place without touching the rest of the database.

**5. Test via Africa's Talking's web simulator** (linked from your sandbox
dashboard) — dial the service code shown against your USSD channel, browse
bills, get a summary, subscribe, vote. Check the dashboard's **SMS Outbox**
for sent messages (the sandbox never delivers to a real phone, by design).

**6. Open the web app.** Just double-click `web/index.html` — no build step,
no server needed for the page itself. It talks to your running API at
`http://localhost:8000` by default (editable at the top of the page if you're
running the API somewhere else).

## Data sourcing — what's automated, what's manual

Here's the honest breakdown, rather than implying more automation than
actually exists:

| Piece | Automated? |
|---|---|
| Decode (bill text → plain language + citations) | Yes — works on any bill text |
| Translate (English → Kiswahili) | Yes |
| SMS/USSD delivery, subscribe, notify, voting | Yes — tested live |
| Free-text SMS question-answering | Yes |
| **Fetching bill text from Kenya Law** | **Partially** — `extract_one_bill.py` is a real, working single-bill extractor (see below); the three bills seeded for the demo were sourced and curated by hand |
| Matching a bill to Mzalendo's stage/sponsor data | Manual for the demo; `extract_one_bill.py` attempts this automatically but the exact search endpoint is unconfirmed and currently returns no match |
| Feeding a freshly-extracted bill into the decode pipeline | **Not yet automated** — `extract_one_bill.py` writes a `.txt`; running that through `decoder.py`/`translator.py`/`seed_bills.py` is a manual next step, by design (see Future Work) |

### About `extract_one_bill.py`

This one's a genuine, live proof of concept. Not a mockup. Run against
`TARGET_TITLE = "The National Coroners Service Bill, 2026"`, here's what
it actually does:
1. Fetches Kenya Law's live bills listing and finds the matching entry
   by link text, not by guessing at URL patterns.
2. Follows it to the bill's page, which Kenya Law renders as a
   JS-loaded PDF viewer for bills. Confirmed by inspecting the real
   page: the actual PDF URL lives in a `data-pdf="..."` attribute, not
   a plain link.
3. Downloads and extracts the PDF's text via PyMuPDF.
4. Attempts a Mzalendo match. Best-effort, and it degrades gracefully
   if that fails.
5. Writes the result to `data/<slug>_extracted.txt`.

Verified: this pulled 63,753 characters from the live Coroners Bill
PDF, and it matched the manually-sourced version already in this repo.
Change `TARGET_TITLE` to try another bill. If it can't find a link, it
prints every bill-like link it *did* find, so retargeting is fast.

## Utility / diagnostic scripts (kept intentionally, not cleanup candidates)

- `translate_only.py <decoded.json>` — translate an already-decoded bill
  without spending a second decode call
- `update_bill_swahili.py <ref_code> <sw.json>` — patch one bill's Kiswahili
  translation into the database in place, no deletion/reseed needed
- `check_ssl_patch.py`, `check_sms_send.py`, `check_swahili_data.py` — direct,
  isolated tests for the SMS send path, SSL configuration, and database state,
  bypassing USSD/ngrok entirely for faster debugging

## A real bug you may hit, and why it's already handled

On some Windows machines, Python's TLS stack fails to connect to
Africa's Talking's sandbox API (`SSL: WRONG_VERSION_NUMBER`), even
though curl and browsers connect just fine. That's a genuine
Python/OpenSSL 3.x mismatch with this specific server's TLS behavior,
not a bug in this code. `ssl_patch.py` addresses part of it.
`sms_client.py`'s `send_sms()` also falls back automatically to
shelling out to `curl.exe` if the normal path fails with an SSL error,
and that fallback is verified working end to end. If you hit this on a
fresh machine and the fallback doesn't trigger, run `check_ssl_patch.py`
for a direct diagnosis.

## Roadmap: local language and cross-country scalability

**Local language expansion (Sheng, Nigerian Pidgin, and beyond).** The
translation pipeline already proved it generalizes. Adding Kiswahili
meant writing one new prompt in `translator.py`, not rebuilding
anything. That same pattern extends to Sheng, Nairobi's urban
vernacular, which a lot of younger, lower-income Kenyans use daily and
actually code-switch into more naturally than formal Kiswahili. It
extends to Nigerian Pidgin too, for reach beyond Kenya. Each one needs
the same care we already gave Kiswahili: real terminology checked
against how it's actually used, not assumed, and a native or fluent
speaker reviewing the output before anyone trusts it. That's exactly
the process that caught the "Wakorona"/COVID-19 ambiguity during this
build. Not a one-time task to skip next time.

**Scalability to other democratic countries, checked rather than
assumed.** Kenya's Parliament follows the Westminster model: First
Reading, Second Reading, Committee Stage, Third Reading, Assent.
Inherited from British colonial-era parliamentary practice. This isn't
unique to Kenya at all. Nigeria's National Assembly follows almost the
exact same structure: First Reading, Second Reading, Committee Stage
with public hearings, Third Reading, Presidential Assent, with a
30-day signing window and a two-thirds override if the President
vetoes [a][b]. The same three-reading pattern holds, with local
variation, across the UK, Canada, Australia, Uganda, India's Lok Sabha,
and most Commonwealth legislatures [c][d].

So the decode mechanism itself, bill text in, structured
plain-language summary with section citations out, should generalize
to these countries with minimal change. The underlying document
structure (numbered clauses, readings, committee stages) is
consistent. One honest limit worth stating plainly: Kenya's
constitutional mandate for public participation (Article 118) is an
unusually strong, explicit legal requirement. Not every Commonwealth
country entrenches citizen input this firmly, even though most provide
some form of committee-stage public hearing. So the "what you can do
and where" part of a decoded summary would need light, per-country
adaptation, not a rebuild, to point citizens at whatever that
country's actual process actually offers.

<sub>Sources: [a] Mondaq, "A Summary of the Legislative Process in Nigeria,"
2022 — mondaq.com/nigeria/constitutional-administrative-law/1222558.
[b] National Assembly of Nigeria, legislative process portal —
nass.gov.ng/themes/newnass/legislative-process.html.
[c] Wikipedia, "Reading (legislature)" — en.wikipedia.org/wiki/Reading_(legislature).
[d] Wikipedia, "Third reading" — modeldiplomat.com/learn/glossary/third-reading
and en.wikipedia.org equivalents.</sub>

## What's deliberately not built (named, not hidden)

- **Live/scheduled scraping.** `extract_one_bill.py` proves the
  mechanism works for one bill on demand. An unattended sync job
  polling Kenya Law on a schedule is future work, left out on purpose
  for a two-day build.
- **Auto-feeding extraction into the decode pipeline.** Both pieces
  exist and both work, but they're not wired together yet. Connecting
  them is a small, named next step. Not a hidden gap.
- **A formal, legally-binding petition mechanism.** The support/oppose
  feature is an honest, simple tally. Stated as such in the web app
  itself.
- **Real OCR.** Text-layer extraction, via PyMuPDF, covers bills that
  have one, and most current Kenya Law bills do. A true OCR fallback
  for scanned, image-only PDFs isn't built.
- **A maintained translation terminology glossary.** One real
  ambiguity, "Wakorona" and its COVID-19 associations, got caught
  through testing and fixed via an explicit prompt rule. A production
  version would need this to scale as a proper glossary, reviewed by a
  fluent Kiswahili speaker, rather than one-off prompt patches.
- **Human moderation** for web app comments. Right now it's a length
  cap and a small denylist, nothing more, and the app says so plainly.

## Environment variables

| Variable | Where it's used | Notes |
|---|---|---|
| `GEMINI_API_KEY` | decode, translate, SMS Q&A | Free tier, no card needed |
| `AT_USERNAME` | SMS/USSD | Always `sandbox` for the sandbox environment |
| `AT_API_KEY` | SMS/USSD | From your AT sandbox dashboard |
