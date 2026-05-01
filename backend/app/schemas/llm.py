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


class TopicClusters(BaseModel):
    """Flat (topic, clusters) pair — OpenAI strict schemas reject `dict[str, …]`
    because dynamic-keyed objects can't satisfy `additionalProperties: false`."""
    topic: str
    clusters: list[Cluster]


class ClusterAnalysisOutput(BaseModel):
    clusters_per_topic: list[TopicClusters] = Field(
        description="按主题分组的 cluster 列表（每项 = topic + 该主题下若干 cluster）"
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


class TopicSummary(BaseModel):
    topic: str
    summary: str


class ReportCompositionOutput(BaseModel):
    title: str
    analysis: FinalAnalysis
    section_summaries: list[TopicSummary] = Field(
        default_factory=list, description="按主题的小结（list of {topic, summary}）"
    )


# ---------------------------------------------------------------------------
# Event curator — classify + merge events across reports
# ---------------------------------------------------------------------------
class EventDecision(BaseModel):
    """One verdict per existing Event row.

    `action` semantics:
      - keep      : event is a real, named event/forum/podcast/article-with-byline.
                    Optionally fill in metadata (canonical_name, kind, host, date).
      - delete    : event name is generic content-type junk (e.g. "研究报告",
                    "LinkedIn Post", "文章") — drop the row, NULL out viewpoint.event_id.
      - merge     : event refers to the same real event as `merge_into_id`.
                    Repoint viewpoints to that id, delete this row.
    """
    event_id: int
    action: Literal["keep", "delete", "merge"]
    merge_into_id: int | None = Field(
        default=None,
        description="只有 action=merge 时填，指向 canonical event 的 id",
    )
    canonical_name: str | None = Field(
        default=None,
        description="若 action=keep，可顺便规范化名称（如把缩写补全）",
    )
    kind: Literal[
        "forum", "interview", "podcast", "keynote",
        "paper", "article", "blog", "other",
    ] | None = None
    host: str | None = None
    date_iso: str | None = Field(
        default=None,
        description="ISO 8601 日期，若能从名字推断出活动日期则填",
    )
    rationale: str = Field(
        default="",
        description="一句话说明判断依据，便于人工核对",
    )


class CuratorOutput(BaseModel):
    decisions: list[EventDecision]
