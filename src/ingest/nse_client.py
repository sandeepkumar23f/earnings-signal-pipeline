import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.config import WATCHLIST, EXCLUDE_KEYWORDS

logger = logging.getLogger("ingest.nse")

NSE_HOME = "https://www.nseindia.com"
NSE_ANNOUNCEMENTS_PAGE = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
NSE_API_URL = "https://www.nseindia.com/api/corporate-announcements"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": NSE_ANNOUNCEMENTS_PAGE,
    "Connection": "keep-alive",
}


def is_concall_transcript(subject: str, description: str, attachment_url: str) -> bool:
    if not attachment_url or not attachment_url.lower().endswith(".pdf"):
        return False
    combined = f"{subject} {description} {attachment_url}".lower()
    if any(bad in combined for bad in EXCLUDE_KEYWORDS):
        return False
    return "transcript" in combined

class NSEClient:
    def __init__(self) -> None:
        self.client = httpx.AsyncClient(
            headers=DEFAULT_HEADERS,
            timeout=25.0,
            follow_redirects=True,
        )
        self._cookies_warmed = False

    async def warm_session(self, force: bool = False) -> None:
        if self._cookies_warmed and not force:
            return
        try:
            await self.client.get(NSE_HOME)
            await asyncio.sleep(0.8)
            await self.client.get(NSE_ANNOUNCEMENTS_PAGE)
            self._cookies_warmed = True
            logger.info("NSE session cookies warmed successfully.")
        except Exception as exc:
            logger.warning(f"Failed to warm NSE session: {exc}")
            self._cookies_warmed = False

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1.5, min=2, max=10),
        retry=retry_if_exception_type((httpx.RequestError, httpx.HTTPStatusError)),
    )
    async def _fetch_symbol_announcements(
        self, symbol: str, from_date: str, to_date: str
    ) -> List[Dict[str, Any]]:
        await self.warm_session()
        params = {
            "index": "equities",
            "symbol": symbol,
            "from_date": from_date,
            "to_date": to_date,
        }
        resp = await self.client.get(NSE_API_URL, params=params)
        if resp.status_code in (401, 403):
            logger.info(f"NSE returned {resp.status_code} for {symbol}, refreshing cookies...")
            await self.warm_session(force=True)
            resp = await self.client.get(NSE_API_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []

    async def fetch_recent_transcripts(self, lookback_days: int = 95) -> List[Dict[str, Any]]:
        """Polls NSE corporate announcements for all watchlist symbols over the lookback window."""
        to_dt = datetime.now()
        from_dt = to_dt - timedelta(days=lookback_days)
        from_str = from_dt.strftime("%d-%m-%Y")
        to_str = to_dt.strftime("%d-%m-%Y")

        discovered: List[Dict[str, Any]] = []

        for item in WATCHLIST:
            symbol = item["nse_symbol"]
            try:
                rows = await self._fetch_symbol_announcements(symbol, from_str, to_str)
                for row in rows:
                    desc = str(row.get("desc", ""))
                    att_text = str(row.get("attchmntText", ""))
                    pdf_url = str(row.get("attchmntFile", "")).strip()
                    xbrl_url = str(row.get("xbrl", "")).strip()

                    if is_concall_transcript(desc, att_text, pdf_url):
                        raw_date = str(row.get("an_dt", "")).split(" ")[0]
                        discovered.append({
                            "company": item["company"],
                            "nse_symbol": symbol,
                            "scrip_code": item["bse_code"],
                            "sector": item["sector"],
                            "source": "NSE",
                            "source_url": pdf_url,
                            "xbrl_url": xbrl_url if xbrl_url.startswith("http") else "",
                            "title": f"{desc} - {att_text}".strip(" -"),
                            "call_date": self._normalize_date(raw_date),
                        })
                await asyncio.sleep(0.6)
            except Exception as exc:
                logger.error(f"NSE fetch failed for {symbol}: {exc}")

        return discovered

    async def download_file(self, url: str, dest_path: Path) -> Optional[Path]:
        if not url:
            return None
        try:
            await self.warm_session()
            resp = await self.client.get(url)
            resp.raise_for_status()
            dest_path.write_bytes(resp.content)
            return dest_path
        except Exception as exc:
            logger.error(f"NSE download failed ({url}): {exc}")
            return None

    @staticmethod
    def _normalize_date(date_str: str) -> str:
        for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return date_str or datetime.now().strftime("%Y-%m-%d")

    async def close(self) -> None:
        await self.client.aclose()