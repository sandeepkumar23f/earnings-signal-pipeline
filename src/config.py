import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
SAMPLES_DIR = DATA_DIR / "samples"
DB_PATH = DATA_DIR / "concall.db"

RAW_DIR.mkdir(parents=True, exist_ok=True)
SAMPLES_DIR.mkdir(parents=True, exist_ok=True)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "120"))
PORT = int(os.getenv("PORT", "8000"))

# 8 companies across 5 sectors (Banking, IT, Auto, Pharma, Conglomerate/Consumer)
WATCHLIST = [
    {"company": "HDFC Bank Limited", "nse_symbol": "HDFCBANK", "bse_code": "500180", "sector": "Banking"},
    {"company": "ICICI Bank Limited", "nse_symbol": "ICICIBANK", "bse_code": "532174", "sector": "Banking"},
    {"company": "Tata Consultancy Services Limited", "nse_symbol": "TCS", "bse_code": "532540", "sector": "IT"},
    {"company": "Infosys Limited", "nse_symbol": "INFY", "bse_code": "500209", "sector": "IT"},
    {"company": "Tata Motors Limited", "nse_symbol": "TATAMOTORS", "bse_code": "500570", "sector": "Auto"},
    {"company": "Mahindra & Mahindra Limited", "nse_symbol": "M&M", "bse_code": "500520", "sector": "Auto"},
    {"company": "Sun Pharmaceutical Industries Limited", "nse_symbol": "SUNPHARMA", "bse_code": "524715", "sector": "Pharma"},
    {"company": "Reliance Industries Limited", "nse_symbol": "RELIANCE", "bse_code": "500325", "sector": "Energy & Retail"},
]

SYMBOL_TO_META = {item["nse_symbol"]: item for item in WATCHLIST}
BSE_TO_META = {item["bse_code"]: item for item in WATCHLIST}

# Strict filters to isolate earnings call transcripts from general investor meet notices
INCLUDE_KEYWORDS = [
    "transcript",
    "earnings call",
    "conference call",
    "concall",
    "post earnings",
    "q1", "q2", "q3", "q4",
]

EXCLUDE_KEYWORDS = [
    "audio recording",
    "video recording",
    "intimation of schedule",
    "schedule of analyst",
    "investor presentation",
    "press release",
]