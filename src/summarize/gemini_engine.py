import asyncio
import logging
from typing import Dict, Any, Tuple, List
from google import genai
from google.genai import types
from google.genai.errors import ServerError, ClientError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, RetryError

from src.config import GEMINI_API_KEY, GEMINI_MODEL
from src.summarize.schema import ConcallSummary

logger = logging.getLogger("summarize.gemini")

SYSTEM_PROMPT = """You are a senior institutional equity research analyst covering Indian listed companies.
Your task is to extract a faithful, high-signal structured summary from an earnings conference call transcript.

STRICT GROUNDING RULES (NON-NEGOTIABLE):
1. Extract ONLY facts, numbers, targets, and statements explicitly present in the provided transcript.
2. NEVER invent, extrapolate, or use outside knowledge. If guidance or a metric is not mentioned on the call, omit it or return an empty list [].
3. Preserve exact currency units (INR Cr, USD Mn, %), basis points (bps), and YoY/QoQ comparisons as spoken.
4. For Notable Q&A, attribute the analyst's name and brokerage/institution accurately when stated in the transcript.
5. Keep TL;DR bullets dense, factual, and scannable (3-5 bullets max)."""


class GeminiSummarizer:
    def __init__(self) -> None:
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY is missing. Set it in your .env file.")
        self.client = genai.Client(api_key=GEMINI_API_KEY)
        # Primary model with automatic failover across active Flash models on 503/429 spikes
        candidates: List[str] = [
            "gemini-3.5-flash",
            "gemini-3.1-flash-lite",
            "gemini-3.7-flash",
            GEMINI_MODEL,
        ]
        self.fallback_models: List[str] = list(dict.fromkeys(candidates))

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=2, min=3, max=8),
        retry=retry_if_exception_type(ServerError),
    )
    def _invoke_model(self, model_name: str, prompt: str) -> ConcallSummary:
        response = self.client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=ConcallSummary,
                temperature=0.1,
            ),
        )
        return ConcallSummary.model_validate_json(response.text)

    def _call_gemini_sync(self, prompt: str) -> ConcallSummary:
        last_err: Exception | None = None
        for model_name in self.fallback_models:
            try:
                return self._invoke_model(model_name, prompt)
            except (ServerError, ClientError, RetryError) as exc:
                logger.warning(f"Model {model_name} unavailable ({exc}); failing over to next model...")
                last_err = exc
                continue
        raise RuntimeError(f"All Gemini fallback models failed. Last error: {last_err}")

    async def summarize_transcript(
        self, transcript_text: str, meta: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], str]:
        """
        Runs structured extraction via Gemini with automatic model failover and renders Markdown.
        Returns (summary_dict, summary_markdown).
        """
        clipped_text = transcript_text[:450_000]

        user_prompt = (
            f"Filing Metadata:\n"
            f"- Company: {meta.get('company')}\n"
            f"- NSE Symbol: {meta.get('nse_symbol')}\n"
            f"- BSE Scrip Code: {meta.get('scrip_code')}\n"
            f"- Filing/Call Date: {meta.get('call_date')}\n"
            f"- Source Exchange: {meta.get('source')}\n"
            f"- Source URL: {meta.get('source_url')}\n\n"
            f"Analyze the following earnings call transcript and populate the required JSON schema:\n\n"
            f"--- TRANSCRIPT START ---\n{clipped_text}\n--- TRANSCRIPT END ---"
        )

        summary_obj: ConcallSummary = await asyncio.to_thread(
            self._call_gemini_sync, user_prompt
        )

        summary_dict = summary_obj.model_dump()
        summary_dict["company"] = meta.get("company", summary_dict["company"])
        summary_dict["scrip_code"] = meta.get("scrip_code", summary_dict["scrip_code"])
        summary_dict["nse_symbol"] = meta.get("nse_symbol", summary_dict["nse_symbol"])
        summary_dict["source"] = meta.get("source", summary_dict["source"])
        summary_dict["source_url"] = meta.get("source_url", summary_dict["source_url"])

        markdown_text = render_markdown_summary(summary_dict)
        return summary_dict, markdown_text


def render_markdown_summary(data: Dict[str, Any]) -> str:
    lines = [
        f"# {data['company']} ({data['nse_symbol']}) — {data['quarter']} Concall Summary",
        "",
        f"**Call Date:** {data['call_date']} | **BSE Scrip:** `{data['scrip_code']}` | "
        f"**Source:** [{data['source']}]({data['source_url']}) | **Tone:** `{data.get('management_tone', 'N/A')}`",
        "",
        "## TL;DR",
    ]
    for item in data.get("tldr", []):
        lines.append(f"- {item}")

    lines.extend(["", "## Key Numbers Called Out", "| Metric | Value | Context |", "| :--- | :--- | :--- |"])
    for m in data.get("key_metrics", []):
        lines.append(f"| {m['metric']} | **{m['value']}** | {m['context']} |")

    lines.extend(["", "## Management Commentary"])
    for item in data.get("management_commentary", []):
        lines.append(f"- {item}")

    lines.extend(["", "## Guidance & Outlook"])
    guidance = data.get("guidance", [])
    if guidance:
        for item in guidance:
            lines.append(f"- {item}")
    else:
        lines.append("- *No explicit quantitative guidance provided on this call.*")

    lines.extend(["", "## Segment / Vertical Performance"])
    for seg in data.get("segment_performance", []):
        lines.append(f"- **{seg['segment']}:** {seg['notes']}")

    lines.extend(["", "## Notable Analyst Q&A"])
    for qa in data.get("notable_qa", []):
        lines.append(f"### Q ({qa['asked_by']}): {qa['question']}")
        lines.append(f"> **Management:** {qa['answer']}")
        lines.append("")

    lines.extend(["## Risks & Concerns Flagged"])
    for r in data.get("risks", []):
        lines.append(f"- {r}")

    return "\n".join(lines).strip() + "\n"