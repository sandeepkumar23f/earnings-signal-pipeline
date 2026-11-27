python -c "from pathlib import Path; Path('README.md').write_text('''# Concall Pulse — Real-Time NSE & BSE Earnings Transcript Pipeline

An unattended, end-to-end financial intelligence pipeline that monitors NSE and BSE corporate filings for listed Indian companies, extracts and cleans earnings conference call transcripts (PDF/XBRL), generates schema-grounded structured JSON and Markdown summaries using Google Gemini, and broadcasts live updates over WebSockets and an analyst web dashboard.

---

## Architecture

\`\`\`text
[ 1. WATCH & INGEST ] [ 2. EXTRACT ] [ 3. SUMMARIZE ] [ 4. SERVE & STREAM ]
NSE cookie-warmed API --> PyMuPDF block-sort --> Gemini Flash (1M ctx) --> SQLite persistence
BSE circuit-breaker Header/footer strip Pydantic JSON schema FastAPI /ws broadcast
SHA-256 deduplication Speaker preservation Multi-model failover Live Analyst UI (/)
\`\`\`

### Module Breakdown

- \`src/config.py\` & \`src/db.py\`: Environment configuration, 8-company multi-sector watchlist (\`HDFCBANK\`, \`ICICIBANK\`, \`TCS\`, \`INFY\`, \`TATAMOTORS\`, \`M&M\`, \`SUNPHARMA\`, \`RELIANCE\`), and async SQLite (\`aiosqlite\`) storage with two-tier SHA-256 deduplication.
- \`src/ingest/\`: Cookie-warmed async \`httpx\` clients for NSE (\`nseindia.com/api/corporate-announcements\`) and BSE (\`api.bseindia.com\`), exponential backoff retries (\`tenacity\`), strict keyword filtering (excluding audio-only/schedule notices), and a per-cycle HTTP 403 circuit-breaker.
- \`src/extract/\`: \`PyMuPDF\` (\`fitz\`) reading-order block sorter for multi-column transcripts, frequency-based boilerplate header/footer removal with regex protection (\`SPEAKER_LABEL_RE\`) for speaker turns (\`Moderator:\`, executive/analyst names), scanned-PDF detection, and optional XBRL XML metadata parsing.
- \`src/summarize/\`: Schema-enforced \`google-genai\` extraction using Pydantic (\`ConcallSummary\`), low-temperature (\`0.1\`) strict grounding prompts, automatic multi-model failover (\`gemini-3.5-flash\` -> \`gemini-3.1-flash-lite\` -> \`gemini-3.7-flash\`) for 429/503 spikes, and deterministic Markdown rendering.
- \`src/serve/\`: Single-process FastAPI server running an \`asyncio\` background poller (\`pipeline_lock\` guarded), \`/ws\` WebSocket broadcaster (\`ConnectionManager\`), REST endpoints (\`/api/filings\`, \`/api/poll-now\`), and a static analyst dashboard.

---

## Quick Start (One Command)

1. **Clone & create virtual environment**
   \`\`\`bash
   git clone https://github.com/sandeepkumar23f/earnings-signal-pipeline.git
   cd earnings-signal-pipeline
   python -m venv .venv

   # Windows PowerShell:

   .\\.venv\\Scripts\\Activate.ps1

   # macOS / Linux:

   source .venv/bin/activate
   \`\`\`

2. **Install dependencies & configure environment**
   \`\`\`bash
   pip install -r requirements.txt
   cp .env.example .env

   # Add your GEMINI_API_KEY inside .env

   \`\`\`

3. **Run the entire pipeline (Watcher + WebSocket + UI)**
   \`\`\`bash
   python main.py
   \`\`\`
   - **Analyst Dashboard:** \`http://localhost:8000\`
   - **Live WebSocket Feed:** \`ws://localhost:8000/ws\` (emits \`{\"event\": \"new_summary\", \"data\": {...}}\` as filings are processed)
   - **Manual Trigger:** \`POST http://localhost:8000/api/poll-now\`

---

## Sample Outputs (\`data/samples/\`)

Pre-generated raw transcript PDFs, structured JSON outputs, and Markdown briefs are committed under \`data/samples/\` across four sectors:

- **Auto:** \`M&M_2026-11-11\` (\`\_transcript.pdf\`, \`\_summary.json\`, \`\_summary.md\`)
- **Pharma:** \`SUNPHARMA_2026-11-04\` (\`\_transcript.pdf\`, \`\_summary.json\`, \`\_summary.md\`)
- **Energy & Retail:** \`RELIANCE_2026-11-01\` (\`\_transcript.pdf\`, \`\_summary.json\`, \`\_summary.md\`)
- **IT Services:** \`INFY_2026-10-28\` (\`\_transcript.pdf\`, \`\_summary.json\`, \`\_summary.md\`)

---

## Key Design Decisions & Trade-Offs

1. **Single-Pass Long-Context Extraction vs. Naive Chunking:** Earnings transcripts run 15-48 pages (~10k-25k tokens). Splitting transcripts into fixed character chunks risks severing Q&A pairs and losing cross-references between opening remarks and analyst follow-ups. Using Gemini Flash's 1M-token context window with Pydantic \`response_schema\` preserves full-call coherence while guaranteeing schema compliance.
2. **Schema Enhancements (\`management_tone\`):** Added a constrained \`management_tone\` field (\`Bullish\`, \`Cautiously Optimistic\`, \`Neutral\`, \`Defensive\`, \`Cautious\`) alongside the core schema fields so downstream consumers can filter or alert on sentiment shifts immediately.
3. **Speaker-Turn Protection During Boilerplate Removal:** Frequency-based header/footer stripping removes lines appearing on >=40% of pages. A dedicated regex (\`SPEAKER_LABEL_RE\`) exempts lines ending in colons (\`Moderator:\`, \`K Krithivasan:\`, analyst attributions) so speaker transitions remain intact for Q&A extraction.
4. **Two-Layer SHA-256 Deduplication:** Dual-listed companies post identical transcripts on both NSE and BSE. \`src/db.py\` deduplicates both before download (\`SHA-256(symbol + date + normalized_title)\`) and after download (\`SHA-256(pdf_bytes)\`), ensuring idempotency across restarts and cross-exchange duplicates.
5. **Single-Process Async Architecture:** Running the background poller as an \`asyncio\` lifespan task inside FastAPI eliminates external broker/worker overhead (Redis/Celery) so the entire stack boots reliably with \`python main.py\`.

---

## Known Limitations & What I'd Do With More Time

- **BSE WAF Blocking:** \`api.bseindia.com\` aggressively blocks automated requests from non-browser/cloud IPs with \`HTTP 403\`. Currently, the BSE client trips a per-cycle circuit-breaker and relies on NSE filings (which cover all dual-listed large/mid-caps). With more time, I would add BSE RSS/XML notice feed parsing or headless browser session rotation.
- **Scanned / Image-Only PDFs:** \`pdf_cleaner.py\` detects image-only PDFs (\`is_scanned=True\`) and skips them rather than feeding empty text to the LLM. Adding a \`pytesseract\` / Gemini Vision multimodal fallback would recover scanned filings.
- **Audio-Only Filings:** Filings that only contain MP3/video links are currently filtered out; adding a Whisper / Gemini audio transcription fallback would capture management commentary before the text transcript is filed.
- **Horizontal Scaling (2,000+ NSE Symbols):** Switching from per-symbol polling to NSE's bulk market-wide announcement feed, migrating SQLite to PostgreSQL (\`pgvector\` for semantic Q&A search), and backing WebSocket broadcasts with Redis Pub/Sub would scale the system across the full listed universe.
  ''', encoding='utf-8'); print('README.md written successfully')"
