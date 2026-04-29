"""Shared LangGraph state TypedDict."""

from datetime import datetime
from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages

from app.providers.base import ProviderCallTrace
from app.schemas.llm import (
    Cluster,
    ExpertCandidate,
    ExtractedViewpoint,
    FinalAnalysis,
    PlannerOutput,
    RawSnippet,
    SubQuery,
)


def merge_lists(a: list, b: list) -> list:
    return (a or []) + (b or [])


def merge_dicts(a: dict, b: dict) -> dict:
    return {**(a or {}), **(b or {})}


class ReportState(TypedDict, total=False):
    # ---- input ----
    report_id: int
    title: str
    focus_topics: list[str]
    time_range_start: datetime
    time_range_end: datetime
    providers_enabled: list[str]
    md_template_id: int | None
    outline_template_id: int | None
    cost_cap_usd: float
    max_reflection_rounds: int

    # ---- planner ----
    plan: PlannerOutput | None
    sub_queries: list[SubQuery]

    # ---- multi-source search ----
    raw_snippets: Annotated[list[RawSnippet], merge_lists]

    # ---- dedup ----
    snippets_clusters: list[dict]   # [{"key_url": str, "snippets": [...], "providers": [...]}]

    # ---- expert discovery ----
    expert_candidates: list[ExpertCandidate]
    discovered_event_names: list[str]

    # ---- viewpoint extraction ----
    extracted_viewpoints: list[ExtractedViewpoint]

    # ---- cluster analysis ----
    clusters_by_topic: dict[str, list[Cluster]]
    section_summaries: dict[str, str]

    # ---- knowledge writer ----
    persisted_expert_ids: list[int]
    persisted_event_ids: list[int]
    persisted_viewpoint_ids: list[int]

    # ---- composer ----
    final_analysis: FinalAnalysis | None
    md_path: str | None
    outline_json_path: str | None
    pdf_path: str | None

    # ---- bookkeeping ----
    provider_traces: Annotated[list[ProviderCallTrace], merge_lists]
    total_cost_usd: float
    total_tokens: int
    errors: Annotated[list[str], merge_lists]
    notes: Annotated[list[str], merge_lists]
    extras: Annotated[dict[str, Any], merge_dicts]
