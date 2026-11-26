from typing import List, Literal
from pydantic import BaseModel, Field


class SegmentPerformance(BaseModel):
    segment: str = Field(description="Business vertical, geography, or product segment name")
    notes: str = Field(description="Specific performance highlights, growth rates, or headwinds grounded in the call")


class KeyMetric(BaseModel):
    metric: str = Field(description="Financial or operational metric name (e.g., Revenue, Operating Margin, NIM, Order Book)")
    value: str = Field(description="Exact figure or percentage stated on the call")
    context: str = Field(description="YoY/QoQ comparison or brief context stated by management")


class NotableQA(BaseModel):
    question: str = Field(description="Concise summary of the analyst's core question")
    answer: str = Field(description="Management's direct response with specific facts/numbers")
    asked_by: str = Field(description="Analyst name and firm if stated, otherwise 'Analyst'")


class ConcallSummary(BaseModel):
    company: str
    scrip_code: str
    nse_symbol: str
    quarter: str = Field(description="Reporting quarter inferred from transcript, e.g., Q2 FY27")
    call_date: str = Field(description="YYYY-MM-DD date of filing or call")
    source: str = Field(description="Exchange source: NSE or BSE")
    source_url: str
    management_tone: Literal["Bullish", "Cautiously Optimistic", "Neutral", "Defensive", "Cautious"] = Field(
        description="Overall management tone inferred strictly from commentary and Q&A"
    )
    tldr: List[str] = Field(
        description="3 to 5 crisp bullet lines summarizing the call for an analyst to read in 20 seconds"
    )
    management_commentary: List[str] = Field(
        description="Key operational highlights, demand trends, and strategic commentary from leadership"
    )
    guidance: List[str] = Field(
        description="Explicit forward-looking targets, margin bands, capex plans, or outlook statements; empty list if none given"
    )
    segment_performance: List[SegmentPerformance] = Field(
        description="Breakdown of how individual verticals, segments, or geographies performed"
    )
    key_metrics: List[KeyMetric] = Field(
        description="Concrete financial and operational numbers explicitly called out during the call"
    )
    notable_qa: List[NotableQA] = Field(
        description="4 to 7 sharpest analyst questions and management's substantive answers"
    )
    risks: List[str] = Field(
        description="Specific macro, regulatory, margin, or execution risks/concerns raised on the call"
    )