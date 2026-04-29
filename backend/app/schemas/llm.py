"""Pydantic schemas for LLM structured outputs.

Each LLM agent node validates against one of these to avoid hallucinated/malformed JSON.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


# ---------------------------------------------------------------------------
# Planner node — decompose theme into sub-queries per language/angle
# ---------------------------------------------------------------------------
class SubQuery(BaseModel):
    text: str
    lang: Literal["zh", "en", "mixed"]
    angle: str = Field(description="视角，如 '专家观点' / '事件回顾' / '数据/统计' / '反对声音'")
    target_providers: list[str] = Field(default_factory=list, description="建议使用的 provider 子集，空则全部")


class PlannerOutput(BaseModel):
    topic_breakdown: list[str] = Field(description="顶层主题分解")
    sub_queries: list[SubQuery]
    suggested_anchor_events: list[str] = Field(default_factory=list, description="建议从哪些事件/论坛去挖人")


# ---------------------------------------------------------------------------
# Search snippet (provider-normalized)
# ---------------------------------------------------------------------------
class RawSnippet(BaseModel):
    title: str | None = None
    snippet: str
    url: str | None = None
    source_domain: str | None = None
    published_at: datetime | None = None
    provider: str
    lang: str | None = None


# ---------------------------------------------------------------------------
# Expert candidate (from ExpertDiscoverer node)
# ---------------------------------------------------------------------------
class ExpertCandidate(BaseModel):
    name: str
    name_zh: str | None = None
    role: str | None = None
    affiliations: list[str] = Field(default_factory=list)
    rationale: str = Field(description="为何被认为对此主题有发言权 / 影响力")
    profile_urls: list[str] = Field(default_factory=list)
    nominated_by_providers: list[str] = Field(default_factory=list)
    relevance_score: float = Field(ge=0.0, le=1.0, default=0.5)


class ExpertDiscoveryOutput(BaseModel):
    candidates: list[ExpertCandidate]
    discovered_events: list[str] = Field(default_factory=list, description="挖人时识别出的新论坛/采访事件")


# ---------------------------------------------------------------------------
# Viewpoint extraction (the 7-tuple)
# ---------------------------------------------------------------------------
class ExtractedViewpoint(BaseModel):
    expert_name: str
    expert_role: str | None = Field(default=None, description="Who: 角色，如 '国家数据局局长'")
    claim_when: datetime | None = Field(default=None, description="When")
    claim_where: str | None = Field(default=None, description="Where: 场合/地点")
    claim_what: str = Field(description="What: 观点摘要")
    claim_quote: str | None = Field(default=None, description="What: 原话引用")
    claim_medium: str | None = Field(default=None, description="Medium: 论坛/采访栏目/文章")
    claim_source_url: str | None = Field(default=None, description="Source: 链接")
    claim_why_context: str | None = Field(default=None, description="Why: 上下文背景")
    claim_lang: str = Field(default="zh")
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


class ViewpointExtractionOutput(BaseModel):
    viewpoints: list[ExtractedViewpoint]


# ---------------------------------------------------------------------------
# Critic (coverage gap detection)
# ---------------------------------------------------------------------------
class CoverageGap(BaseModel):
    dimension: Literal["geography", "stance", "influence_tier", "time", "language"]
    description: str
    suggested_query: str
    suggested_providers: list[str] = Field(default_factory=list)


class CriticOutput(BaseModel):
    coverage_ok: bool
    new_coverage_vs_prev: float = Field(
        ge=0.0, le=1.0, default=0.0,
        description="相比上轮新增的覆盖比例，<0.05 应停止反思",
    )
    gaps: list[CoverageGap] = Field(default_factory=list)
    rationale: str


# ---------------------------------------------------------------------------
# Cluster analyzer (consensus / dissent / spotlight / insight)
# ---------------------------------------------------------------------------
class Cluster(BaseModel):
    label: str
    kind: Literal["consensus", "dissent", "spotlight", "insight"]
    summary_md: str
    viewpoint_indices: list[int] = Field(description="对应输入 viewpoints 数组的下标")


class ClusterAnalysisOutput(BaseModel):
    clusters_per_topic: dict[str, list[Cluster]] = Field(
        description="key=topic_name, value=该主题下若干 cluster"
    )


# ---------------------------------------------------------------------------
# Final report composition (executive + analysis bundle)
# ---------------------------------------------------------------------------
class FinalAnalysis(BaseModel):
    executive_summary: str
    executive_summary_bullets: list[str] = Field(default_factory=list)
    consensus: list[str] = Field(default_factory=list)
    dissent: list[str] = Field(default_factory=list)
    spotlight: list[str] = Field(default_factory=list)
    insight: list[str] = Field(default_factory=list)


class ReportCompositionOutput(BaseModel):
    title: str
    analysis: FinalAnalysis
    section_summaries: dict[str, str] = Field(
        default_factory=dict, description="key=topic_name, value=该主题的小结"
    )
