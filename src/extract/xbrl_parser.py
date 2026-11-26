import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict

logger = logging.getLogger("extract.xbrl")

TAG_MAP = {
    "NameOfTheCompany": "company",
    "Symbol": "nse_symbol",
    "ScripCode": "scrip_code",
    "DateOfMeeting": "call_date",
    "DateOfEvent": "call_date",
    "QuarterEnded": "quarter",
    "FinancialYear": "financial_year",
}


def parse_xbrl_metadata(xbrl_path: Path) -> Dict[str, str]:
    """Extracts structured corporate metadata from an NSE/BSE XBRL XML filing."""
    if not xbrl_path or not xbrl_path.exists():
        return {}

    metadata: Dict[str, str] = {}
    try:
        tree = ET.parse(str(xbrl_path))
        root = tree.getroot()
        for elem in root.iter():
            # Strip XML namespace prefix: {http://...}TagName -> TagName
            local_name = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if local_name in TAG_MAP and elem.text and elem.text.strip():
                key = TAG_MAP[local_name]
                if key not in metadata:
                    metadata[key] = elem.text.strip()
    except Exception as exc:
        logger.warning(f"XBRL parse skipped for {xbrl_path.name}: {exc}")

    return metadata