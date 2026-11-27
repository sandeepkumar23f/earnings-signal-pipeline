import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.config import WATCHLIST, EXCLUDE_KEYWORDS

logger = logging.getLogger("ingest.bse")

BSE_HOME = "https://www.bseindia.com"
BSE_ANN_PAGE = "https://www.bseindia.com/corporates/ann.html"
BSE_API_URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
BSE_ATTACH_LIVE = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/"
BSE_ATTACH_HIS = "https://www.bseindia.com/xml-data/corpfiling/AttachHis/"

BSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.bseindia.com",
    "Referer": "https://www.bseindia.com/corporates/ann.html",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}


def is_bse_concall_transcript(headline: str, subcat: str, attachment_name: str) -> bool:
    if not attachment_name or not attachment_name.lower().endswith(".pdf"):
        return False
    combined = f"{headline} {subcat}".lower()
    if any(bad in combined for bad in EXCLUDE_KEYWORDS):
        return False
    strong_hits = ["transcript", "earnings call", "conference call", "concall"]
    return any(k in combined for k in strong_hits)


class BSEClient:
    def __init__(self) -> None:
        self.client = httpx.AsyncClient(
            headers=BSE_HEADERS,
            timeout=25.0,
            follow_redirects=True,
        )
        self._warmed = False
        self._blocked_this_cycle = False

    async def warm_session(self, force: bool = False) -> None:
        if self._warmed and not force:
            return
        try:
            await self.client.get(BSE_HOME)
            await asyncio.sleep(0.5)
            await self.client.get(BSE_ANN_PAGE)
            self._warmed = True
        except Exception as exc:
            logger.warning(f"BSE session warmup failed: {exc}")
            self._warmed = False

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1.5, min=1, max=5),
        retry=retry_if_exception_type(httpx.RequestError),
    )
    async def _fetch_scrip_announcements(
        self, scrip_code: str, prev_date: str, to_date: str
    ) -> List[Dict[str, Any]]:
        await self.warm_session()
        params = {
            "pageno": "1",
            "strCat": "-1",
            "strPrevDate": prev_date,
            "strToDate": to_date,
            "strSearch": "P",
            "strScrip": scrip_code,
            "strType": "C",
        }
        resp = await self.client.get(BSE_API_URL, params=params)
        if resp.status_code in (401, 403):
            await self.warm_session(force=True)
            resp = await self.client.get(BSE_API_URL, params=params)
        if resp.status_code == 403:
            self._blocked_this_cycle = True
            logger.info("BSE API WAF blocked automated requests (HTTP 403); tripping circuit-breaker for this cycle.")
            return []
        if resp.status_code != 200:
            logger.warning(f"BSE API returned HTTP {resp.status_code} for {scrip_code}")
            return []
        payload = resp.json()
        return payload.get("Table", []) if isinstance(payload, dict) else []

    async def fetch_recent_transcripts(self, lookback_days: int = 95) -> List[Dict[str, Any]]:
        self._blocked_this_cycle = False
        to_dt = datetime.now()
        from_dt = to_dt - timedelta(days=lookback_days)
        prev_str = from_dt.strftime("%Y%m%d")
        to_str = to_dt.strftime("%Y%m%d")

        discovered: List[Dict[str, Any]] = []

        for item in WATCHLIST:
            if self._blocked_this_cycle:
                break
            bse_code = item["bse_code"]
            try:
                rows = await self._fetch_scrip_announcements(bse_code, prev_str, to_str)
                for row in rows:
                    headline = str(row.get("NEWSSUB", ""))
                    subcat = str(row.get("SUBCATNAME", ""))
                    att_name = str(row.get("ATTACHMENTNAME", "")).strip()

                    if is_bse_concall_transcript(headline, subcat, att_name):
                        raw_dt = str(row.get("NEWS_DT", "")).split("T")[0]
                        pdf_url = f"{BSE_ATTACH_LIVE}{att_name}"
                        discovered.append({
                            "company": item["company"],
                            "nse_symbol": item["nse_symbol"],
                            "scrip_code": bse_code,
                            "sector": item["sector"],
                            "source": "BSE",
                            "source_url": pdf_url,
                            "fallback_url": f"{BSE_ATTACH_HIS}{att_name}",
                            "xbrl_url": "",
                            "title": headline.strip(),
                            "call_date": raw_dt or datetime.now().strftime("%Y-%m-%d"),
                        })
                await asyncio.sleep(0.5)
            except Exception as exc:
                logger.warning(f"BSE fetch skipped for {bse_code} ({item['nse_symbol']}): {exc}")

        return discovered

    async def download_file(
        self, url: str, dest_path: Path, fallback_url: Optional[str] = None
    ) -> Optional[Path]:
        for target in [url, fallback_url]:
            if not target:
                continue
            try:
                resp = await self.client.get(target)
                if resp.status_code == 200 and len(resp.content) > 1024:
                    dest_path.write_bytes(resp.content)
                    return dest_path
            except Exception as exc:
                logger.warning(f"BSE download attempt failed for {target}: {exc}")
        return None

    async def close(self) -> None:
        await self.client.aclose()