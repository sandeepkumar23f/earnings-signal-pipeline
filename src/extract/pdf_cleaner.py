import re
import logging
from collections import Counter
from pathlib import Path
from typing import Dict, Any, List
import fitz  # PyMuPDF

logger = logging.getLogger("extract.pdf")

PAGE_NUM_RE = re.compile(
    r"^\s*(page\s+\d+(\s+of\s+\d+)?|\d+\s*/\s*\d+|\-\s*\d+\s*\-)\s*$",
    re.IGNORECASE,
)

# Preserve speaker turns like "Moderator:", "K Krithivasan:", "Analyst - Morgan Stanley:"
SPEAKER_LABEL_RE = re.compile(r"^[A-Z][A-Za-z0-9\s\.\-\(\)&/,]{1,65}:\s*$")


def extract_clean_transcript(pdf_path: Path) -> Dict[str, Any]:
    """
    Extracts clean, reading-order-preserving text from earnings call PDFs.
    Strips repeated headers/footers and page numbers while preserving speaker labels.
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    doc = fitz.open(str(pdf_path))
    num_pages = len(doc)
    pages_lines: List[List[str]] = []
    line_frequency: Counter = Counter()

    for page in doc:
        blocks = page.get_text("blocks")
        text_blocks = [b for b in blocks if b[6] == 0 and b[4].strip()]
        text_blocks.sort(key=lambda b: (round(b[1] / 12), round(b[0] / 20)))

        page_lines: List[str] = []
        for b in text_blocks:
            for raw_line in b[4].splitlines():
                cleaned = re.sub(r"\s+", " ", raw_line).strip()
                if not cleaned or PAGE_NUM_RE.match(cleaned):
                    continue
                page_lines.append(cleaned)

        pages_lines.append(page_lines)
        for unique_line in set(page_lines):
            # Never count speaker labels as repeating headers/footers
            if len(unique_line) <= 120 and not SPEAKER_LABEL_RE.match(unique_line):
                line_frequency[unique_line] += 1

    doc.close()

    repeat_threshold = max(3, int(num_pages * 0.4))
    boilerplate_lines = {
        line for line, count in line_frequency.items() if count >= repeat_threshold
    }

    cleaned_pages: List[str] = []
    for page_lines in pages_lines:
        filtered = [ln for ln in page_lines if ln not in boilerplate_lines]
        cleaned_pages.append("\n".join(filtered))

    full_text = "\n\n".join(cleaned_pages).strip()
    full_text = re.sub(r"\n{3,}", "\n\n", full_text)

    is_scanned = num_pages > 0 and len(full_text) < (num_pages * 120)
    if is_scanned:
        logger.warning(
            f"{pdf_path.name} appears to be scanned/image-only ({len(full_text)} chars across {num_pages} pages)."
        )

    return {
        "text": full_text,
        "page_count": num_pages,
        "char_count": len(full_text),
        "is_scanned": is_scanned,
        "stripped_headers": list(boilerplate_lines)[:10],
    }