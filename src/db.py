import json
import hashlib
import aiosqlite
from typing import Optional, List, Dict, Any
from src.config import DB_PATH

async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS filings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dedup_key TEXT UNIQUE NOT NULL,
                pdf_hash TEXT,
                company TEXT NOT NULL,
                scrip_code TEXT,
                nse_symbol TEXT,
                quarter TEXT,
                call_date TEXT,
                source TEXT NOT NULL,
                source_url TEXT NOT NULL,
                pdf_path TEXT,
                summary_json TEXT NOT NULL,
                summary_md TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

def make_dedup_key(nse_symbol: str, call_date: str, title_hint: str) -> str:
    raw = f"{nse_symbol.upper()}|{call_date.strip()}|{title_hint.lower()[:40]}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

def compute_file_hash(file_path: str) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

async def is_already_processed(dedup_key: str, pdf_hash: Optional[str] = None) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        if pdf_hash:
            cursor = await db.execute(
                "SELECT 1 FROM filings WHERE dedup_key = ? OR pdf_hash = ? LIMIT 1",
                (dedup_key, pdf_hash),
            )
        else:
            cursor = await db.execute(
                "SELECT 1 FROM filings WHERE dedup_key = ? LIMIT 1",
                (dedup_key,),
            )
        row = await cursor.fetchone()
        return row is not None

async def save_filing(record: Dict[str, Any]) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT OR IGNORE INTO filings (
                dedup_key, pdf_hash, company, scrip_code, nse_symbol,
                quarter, call_date, source, source_url, pdf_path,
                summary_json, summary_md
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["dedup_key"],
                record.get("pdf_hash"),
                record["company"],
                record.get("scrip_code", ""),
                record.get("nse_symbol", ""),
                record.get("quarter", ""),
                record.get("call_date", ""),
                record["source"],
                record["source_url"],
                record.get("pdf_path", ""),
                json.dumps(record["summary_json"]),
                record["summary_md"],
            ),
        )
        await db.commit()
        return cursor.lastrowid

async def get_all_filings(limit: int = 50) -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM filings ORDER BY call_date DESC, id DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        results = []
        for r in rows:
            item = dict(r)
            item["summary_json"] = json.loads(item["summary_json"])
            results.append(item)
        return results