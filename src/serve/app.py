import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Dict, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.config import POLL_INTERVAL_SECONDS, RAW_DIR, SAMPLES_DIR
from src.db import init_db, make_dedup_key, compute_file_hash, is_already_processed, save_filing, get_all_filings
from src.ingest.nse_client import NSEClient
from src.ingest.bse_client import BSEClient
from src.extract.pdf_cleaner import extract_clean_transcript
from src.extract.xbrl_parser import parse_xbrl_metadata
from src.summarize.gemini_engine import GeminiSummarizer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("serve.app")

STATIC_DIR = Path(__file__).resolve().parent / "static"


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket client connected. Active subscribers: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket client disconnected. Active subscribers: {len(self.active_connections)}")

    async def broadcast(self, message: Dict[str, Any]) -> None:
        stale: List[WebSocket] = []
        for ws in self.active_connections:
            try:
                await ws.send_json(message)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(ws)


manager = ConnectionManager()
pipeline_lock = asyncio.Lock()


async def run_ingestion_cycle(lookback_days: int = 95, max_new_per_cycle: int = 8) -> int:
    """Fetches new NSE/BSE filings, deduplicates, extracts text, summarizes via Gemini, and broadcasts over WS."""
    if pipeline_lock.locked():
        logger.info("Ingestion cycle already in progress; skipping overlap.")
        return 0

    async with pipeline_lock:
        nse = NSEClient()
        bse = BSEClient()
        summarizer = GeminiSummarizer()
        processed_count = 0

        try:
            nse_filings, bse_filings = await asyncio.gather(
                nse.fetch_recent_transcripts(lookback_days=lookback_days),
                bse.fetch_recent_transcripts(lookback_days=lookback_days),
            )
            candidates = nse_filings + bse_filings
            logger.info(f"Poll discovered {len(candidates)} candidate transcript filings across NSE/BSE.")

            for item in candidates:
                if processed_count >= max_new_per_cycle:
                    break

                dedup_key = make_dedup_key(item["nse_symbol"], item["call_date"], item["title"])
                if await is_already_processed(dedup_key):
                    continue

                pdf_filename = f"{item['nse_symbol']}_{item['call_date']}_{item['source']}.pdf"
                pdf_path = RAW_DIR / pdf_filename

                if not pdf_path.exists():
                    downloaded = (
                        await nse.download_file(item["source_url"], pdf_path)
                        if item["source"] == "NSE"
                        else await bse.download_file(item["source_url"], pdf_path, item.get("fallback_url"))
                    )
                    if not downloaded:
                        continue

                pdf_hash = compute_file_hash(str(pdf_path))
                if await is_already_processed(dedup_key, pdf_hash=pdf_hash):
                    continue

                # Optional XBRL metadata enrichment
                if item.get("xbrl_url"):
                    xbrl_path = RAW_DIR / f"{item['nse_symbol']}_{item['call_date']}.xml"
                    if await nse.download_file(item["xbrl_url"], xbrl_path):
                        xbrl_meta = parse_xbrl_metadata(xbrl_path)
                        item.update({k: v for k, v in xbrl_meta.items() if v})

                extracted = extract_clean_transcript(pdf_path)
                if extracted["is_scanned"] or extracted["char_count"] < 500:
                    logger.warning(f"Skipping {pdf_filename}: insufficient extractable text (scanned PDF).")
                    continue

                logger.info(f"Summarizing {item['nse_symbol']} ({item['call_date']}) [{extracted['page_count']} pages]...")
                summary_json, summary_md = await summarizer.summarize_transcript(extracted["text"], item)

                record = {
                    "dedup_key": dedup_key,
                    "pdf_hash": pdf_hash,
                    "company": item["company"],
                    "scrip_code": item["scrip_code"],
                    "nse_symbol": item["nse_symbol"],
                    "quarter": summary_json.get("quarter", ""),
                    "call_date": item["call_date"],
                    "source": item["source"],
                    "source_url": item["source_url"],
                    "pdf_path": str(pdf_path),
                    "summary_json": summary_json,
                    "summary_md": summary_md,
                }
                row_id = await save_filing(record)
                if row_id:
                    processed_count += 1
                    await manager.broadcast({
                        "event": "new_summary",
                        "data": {
                            "id": row_id,
                            "company": record["company"],
                            "nse_symbol": record["nse_symbol"],
                            "scrip_code": record["scrip_code"],
                            "quarter": record["quarter"],
                            "call_date": record["call_date"],
                            "source": record["source"],
                            "source_url": record["source_url"],
                            "summary_json": summary_json,
                            "summary_md": summary_md,
                        },
                    })
                    logger.info(f"Broadcasted new summary for {item['nse_symbol']} ({record['quarter']}).")
                    await asyncio.sleep(2.0)  # Gentle pacing for Gemini free-tier RPM

        except Exception as exc:
            logger.error(f"Watcher cycle error: {exc}")
        finally:
            await nse.close()
            await bse.close()

        return processed_count


async def background_watcher() -> None:
    await asyncio.sleep(2)
    while True:
        await run_ingestion_cycle(lookback_days=95, max_new_per_cycle=8)
        logger.info(f"Sleeping {POLL_INTERVAL_SECONDS}s until next NSE/BSE poll...")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    watcher_task = asyncio.create_task(background_watcher())
    yield
    watcher_task.cancel()


app = FastAPI(title="Concall Pulse — Real-Time NSE/BSE Earnings Intelligence", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/api/filings")
async def list_filings() -> JSONResponse:
    filings = await get_all_filings(limit=50)
    return JSONResponse({"count": len(filings), "filings": filings})


@app.post("/api/poll-now")
async def trigger_poll() -> JSONResponse:
    added = await run_ingestion_cycle(lookback_days=95, max_new_per_cycle=4)
    return JSONResponse({"status": "ok", "newly_processed": added})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive and handle optional client pings
            msg = await websocket.receive_text()
            if msg.strip().lower() == "ping":
                await websocket.send_json({"event": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(websocket)