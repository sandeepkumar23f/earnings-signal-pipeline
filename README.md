# Concall Pulse

Concall Pulse is an end-to-end Python pipeline that watches NSE and BSE corporate filings, identifies earnings conference-call transcripts, downloads and cleans their PDFs, generates structured and Markdown summaries with Google Gemini, stores processed filings in SQLite, and exposes a dashboard and WebSocket feed.

The project uses eight Indian listed companies across Banking, IT, Auto, Pharma, and Energy/Retail.

## Pipeline

```text
NSE/BSE filing APIs
        |
        v
Candidate filtering -> PDF download -> SHA-256 deduplication
        |
        v
PyMuPDF text extraction -> cleaning -> scanned-PDF detection
        |
        v
Gemini structured summarization -> Pydantic validation
        |
        v
SQLite persistence -> FastAPI REST/UI -> WebSocket broadcast
```

## Features

- Polls NSE and BSE filings for the configured watchlist.
- Detects transcript-related PDF filings while excluding audio, video, scheduling, and presentation notices.
- Downloads PDF attachments with headers, sessions, retries, exchange pacing, and a BSE 403 circuit-breaker.
- Deduplicates filings by a normalized metadata key and downloaded PDF hash.
- Cleans repeated headers and footers while preserving speaker labels.
- Detects image-only PDFs that cannot currently be processed by text extraction.
- Optionally extracts company and filing metadata from XBRL XML.
- Generates:
  - Schema-constrained JSON.
  - Human-readable Markdown.
  - An analyst-facing management-tone label.
- Persists results in SQLite.
- Automatically polls at a configurable interval.
- Provides a manual poll endpoint.
- Streams every newly processed filing to WebSocket subscribers.
- Provides a browser dashboard for browsing existing and live results.

## Project Structure

```text
main.py                     Uvicorn entry point
src/config.py               Watchlist and environment configuration
src/db.py                   SQLite schema and persistence helpers
src/ingest/nse_client.py    NSE cookie warming and filing discovery
src/ingest/bse_client.py    BSE filing discovery and attachment download
src/extract/pdf_cleaner.py  PDF extraction and boilerplate removal
src/extract/xbrl_parser.py  Optional XBRL metadata parsing
src/summarize/schema.py     Pydantic output contract
src/summarize/gemini_engine.py
                            Gemini invocation and Markdown rendering
src/serve/app.py            Background watcher, REST routes, and WebSockets
src/serve/static/index.html Analyst dashboard
data/samples/               Committed sample PDFs and summaries
```

## Watchlist

| Company | NSE symbol | BSE scrip | Sector |
|---|---|---|---|
| HDFC Bank | HDFCBANK | 500180 | Banking |
| ICICI Bank | ICICIBANK | 532174 | Banking |
| Tata Consultancy Services | TCS | 532540 | IT |
| Infosys | INFY | 500209 | IT |
| Tata Motors | TATAMOTORS | 500570 | Auto |
| Mahindra & Mahindra | M&M | 500520 | Auto |
| Sun Pharmaceutical Industries | SUNPHARMA | 524715 | Pharma |
| Reliance Industries | RELIANCE | 500325 | Energy/Retail |

## Requirements

- Python 3.10 or newer
- Internet access to NSE, BSE, and Google Gemini
- A Gemini API key

The dependencies are listed in `requirements.txt`:

- FastAPI and Uvicorn
- httpx and tenacity
- PyMuPDF
- Google Gen AI SDK
- Pydantic
- aiosqlite
- python-dotenv

## Setup

### Windows PowerShell

```powershell
git clone https://github.com/sandeepkumar23f/earnings-signal-pipeline.git
cd earnings-signal-pipeline

python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1

python -m pip install --upgrade pip
pip install -r requirements.txt

Copy-Item .env.example .env
```

### macOS/Linux

```bash
git clone https://github.com/sandeepkumar23f/earnings-signal-pipeline.git
cd earnings-signal-pipeline

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
pip install -r requirements.txt

cp .env.example .env
```

Edit `.env`:

```dotenv
GEMINI_API_KEY=your_api_key
POLL_INTERVAL_SECONDS=120
PORT=8000
```

`GEMINI_API_KEY` is required. The polling interval and port have defaults but can be changed for local use.

## Run the Complete Pipeline

One command starts the FastAPI application, watcher, dashboard, REST API, and WebSocket server:

```bash
python main.py
```

Open:

- Dashboard: `http://localhost:8000/`
- Filings API: `http://localhost:8000/api/filings`
- Manual poll: `POST http://localhost:8000/api/poll-now`
- WebSocket: `ws://localhost:8000/ws`

A WebSocket client receives:

```json
{
  "event": "new_summary",
  "data": {
    "company": "Example Ltd",
    "nse_symbol": "EXAMPLE",
    "quarter": "Q1 FY27",
    "call_date": "2026-11-01",
    "summary_json": {},
    "summary_md": "# Summary"
  }
}
```

The dashboard also reconnects automatically if the WebSocket connection is interrupted.

## Output Schema

The Gemini response is validated against `src/summarize/schema.py`. The schema includes:

- Company, symbol, scrip code, quarter, filing date, source, and source URL.
- Management tone.
- Three to five TL;DR bullet points.
- Management commentary.
- Guidance and outlook.
- Segment performance.
- Key metrics.
- Notable analyst Q&A.
- Risks and concerns.

The example schema is fixed in code rather than inferred at runtime. `management_tone` is an assignment-enhancing field with a constrained set of values:

```text
Bullish
Cautiously Optimistic
Neutral
Defensive
Cautious
```

The schema makes downstream consumption predictable and allows the UI to filter or highlight management tone.

## Sample Outputs

Complete raw transcript PDFs, structured JSON summaries, and Markdown summaries are committed for four companies:

| Sector | Company | Quarter | Files |
|---|---|---|---|
| IT | Infosys | Q2 FY27 | [PDF](data/samples/INFY_2026-10-28_transcript.pdf), [JSON](data/samples/INFY_2026-10-28_summary.json), [Markdown](data/samples/INFY_2026-10-28_summary.md) |
| Auto | Mahindra & Mahindra | Q2 FY27 | [PDF](data/samples/M&M_2026-11-11_transcript.pdf), [JSON](data/samples/M&M_2026-11-11_summary.json), [Markdown](data/samples/M&M_2026-11-11_summary.md) |
| Energy/Retail | Reliance Industries | Q2 FY2027 | [PDF](data/samples/RELIANCE_2026-11-01_transcript.pdf), [JSON](data/samples/RELIANCE_2026-11-01_summary.json), [Markdown](data/samples/RELIANCE_2026-11-01_summary.md) |
| Pharma | Sun Pharmaceutical Industries | Q2 FY27 | [PDF](data/samples/SUNPHARMA_2026-11-04_transcript.pdf), [JSON](data/samples/SUNPHARMA_2026-11-04_summary.json), [Markdown](data/samples/SUNPHARMA_2026-11-04_summary.md) |

## Design Decisions and Trade-offs

### One-pass extraction for assignment-scale transcripts

The current implementation sends up to 450,000 extracted characters to Gemini. This reduces transcript fragmentation and preserves Q&A context better than fixed character splitting. It relies on Gemini's large context window and is suitable for the present 15-48-page sample transcripts.

The implementation does not yet merge independently summarized chunks. For transcripts longer than the configured limit, the safest improvement is overlapping chunking followed by a final de-duplication and merge pass.

### Strict structured LLM output

Gemini is called with JSON MIME type and a Pydantic response schema. The low temperature (`0.1`) and grounding prompt reduce unsupported output, while Pydantic validates types and enum values.

Prompt grounding is a safeguard, not a mathematical guarantee. The next implementation step should add a verification pass that checks extracted claims against source text and records page references.

### PDF reading order

PyMuPDF text blocks are sorted approximately by vertical position and then horizontal position. Repeated lines occurring on at least 40 percent of pages are removed as potential headers or footers. A regex protects lines resembling speaker turns, such as `Moderator:`.

This is fast and works for many standard disclosure PDFs. It is heuristic rather than a complete two-column document-layout engine.

### Deduplication

Each filing has two deduplication mechanisms:

1. A SHA-256 metadata key based on symbol, date, and title.
2. A SHA-256 hash of the actual downloaded PDF bytes.

The first check avoids unnecessary downloads. The second catches cross-exchange duplicates that have different URLs or filenames.

### Single-process architecture

FastAPI, SQLite, the background watcher, and WebSockets run in the same process. `asyncio.Lock` prevents polling cycles from overlapping. This eliminates Redis/Celery setup and allows the entire application to start with `python main.py`.

SQLite is suitable for this take-home deployment but should be replaced by PostgreSQL for multiple application workers or a larger filing universe.

## Real-time Behavior

The FastAPI lifespan handler starts `background_watcher()`. It waits two seconds, runs one ingestion cycle, and then waits for `POLL_INTERVAL_SECONDS` before polling again.

The cycle:

1. Fetches watchlist filings from NSE and BSE.
2. Filters candidate PDFs.
3. Checks metadata deduplication.
4. Downloads and hashes the PDF.
5. Checks the PDF hash against existing filings.
6. Extracts and validates text.
7. Generates and validates JSON.
8. Renders Markdown.
9. Saves the result.
10. Broadcasts it to WebSocket subscribers.

## Security and Configuration

- API keys are loaded from `.env`.
- `.env` is excluded by `.gitignore`.
- No API key or credential is committed.
- The manual poll endpoint should be protected or disabled when deployed publicly.
- CORS and public WebSocket access should be restricted for production.

## Known Limitations

### BSE access

BSE is more sensitive to automated requests than NSE. During runtime validation, `api.bseindia.com` returned HTTP 403 for the BSE WAF and the client tripped its per-cycle circuit-breaker. NSE continued to discover filings.

The project behaves conservatively: it stops repeated BSE requests for the cycle instead of generating an artificial failure loop.

### Scanned PDFs

Image-only PDFs are detected and skipped rather than sent to the LLM with no text. OCR is not yet implemented.

### Audio-only filings

The transcript filter excludes audio and video recording notices. Speech-to-text for those filings is not implemented.

### Long-context handling

The current 450,000-character limit is a single-pass trade-off rather than a complete chunked map-reduce implementation.

### Exchange and network coverage

Exchange HTML/API responses and automated IP behavior can change. Retries help transient errors, but this is not a guaranteed all-markets or 24/7 BSE feed.

### No automated test suite

The repository should add tests before production use.

## What I Would Add with More Time

1. **True chunked summarization**
   - Split by pages or speaker turns.
   - Use overlap to retain Q&A context.
   - Merge and deduplicate facts.

2. **Evidence and hallucination verification**
   - Record source page references.
   - Re-check each extracted claim against the transcript.
   - Empty or reject unsupported fields.

3. **OCR fallback**
   - Use Tesseract or a vision model for image-only pages.
   - Report OCR confidence and keep native-text extraction when available.

4. **More reliable BSE discovery**
   - Prefer official RSS/XML or bulk feeds where practical.
   - Use browser fallback only if permitted and necessary.
   - Expose exchange health status.

5. **Testing**
   - Exchange announcement-classification tests.
   - PDF cleaner and scanned-PDF tests.
   - XBRL and malformed-input tests.
   - Deduplication tests.
   - Pydantic and API route tests.
   - WebSocket broadcast tests.

6. **Production scaling**
   - PostgreSQL instead of SQLite.
   - Queue-based ingest, extract, summarize, and serve stages.
   - Object storage for PDFs.
   - Redis Pub/Sub or a managed WebSocket broker.
   - Docker Compose and health checks.

7. **Operations**
   - Structured logs and metrics.
   - Retry/dead-letter handling.
   - Authentication for manual poll and private routes.
   - Exchange-specific status and last-success timestamps.

## Verified Runtime Status

The following checks were performed locally:

- Python sources compiled successfully.
- FastAPI/Uvicorn started successfully on port 8000.
- Dashboard route returned HTTP 200.
- `/api/filings` returned persisted filing records.
- SQLite contained processed filing records.
- The Infosys sample PDF extracted 48 pages and 100,778 characters without being detected as scanned.
- An initial runtime poll discovered 7 NSE candidate filings.
- The BSE API returned HTTP 403 and correctly activated the BSE per-cycle circuit-breaker.
