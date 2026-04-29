"""SQLModel definitions for Insights Collect.

Models double as DB schema and API response shape (since SQLModel = Pydantic + SQLAlchemy).
For payload-shape variations create thin Pydantic schemas under app.schemas instead.
"""

from datetime import datetime
from enum import Enum

from sqlmodel import Field, SQLModel

from app.db.types import embedding_field, json_field, str_array_field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class EventKind(str, Enum):
    forum = "forum"
    interview = "interview"
    podcast = "podcast"
    keynote = "keynote"
    paper = "paper"
    article = "article"
    blog = "blog"
    other = "other"


class SourceKind(str, Enum):
    news = "news"
    social = "social"
    blog = "blog"
    podcast = "podcast"
    paper = "paper"
    video = "video"
    other = "other"


class TemplateKind(str, Enum):
    md_report = "md_report"
    ppt_outline = "ppt_outline"
    section = "section"


class SkillKind(str, Enum):
    search = "search"
    extract = "extract"
    analyze = "analyze"
    plan = "plan"


class ReportKind(str, Enum):
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"
    adhoc = "adhoc"


class ReportStatus(str, Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class ClusterKind(str, Enum):
    consensus = "consensus"
    dissent = "dissent"
    spotlight = "spotlight"
    insight = "insight"


# ---------------------------------------------------------------------------
# Provider credentials (UI-managed, .env fallback)
# ---------------------------------------------------------------------------
class ProviderCredential(SQLModel, table=True):
    __tablename__ = "provider_credentials"

    id: int | None = Field(default=None, primary_key=True)
    provider: str = Field(index=True, unique=True, description="anthropic / openai / gemini / grok / perplexity / qwen / deepseek")
    api_key: str = ""
    base_url: str | None = None
    default_model: str | None = None
    enabled: bool = True
    last_tested_at: datetime | None = None
    test_status: str | None = None  # ok | error | unknown
    test_message: str | None = None
    extra: dict | None = json_field(default=None)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------
class Topic(SQLModel, table=True):
    __tablename__ = "topics"

    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(index=True, unique=True)
    name: str
    parent_id: int | None = Field(default=None, foreign_key="topics.id", index=True)
    description: str | None = None
    embedding: list[float] | None = embedding_field()
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Experts
# ---------------------------------------------------------------------------
class Expert(SQLModel, table=True):
    __tablename__ = "experts"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    name_zh: str | None = Field(default=None, index=True)
    aliases: list[str] | None = str_array_field(default=None)
    bio: str | None = None
    domains: list[str] | None = str_array_field(default=None)
    affiliations: list[str] | None = str_array_field(default=None)
    profile_urls: list[str] | None = str_array_field(default=None)
    influence_scores: dict | None = json_field(default=None, nullable=True)
    embedding: list[float] | None = embedding_field()
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ExpertAlias(SQLModel, table=True):
    __tablename__ = "expert_aliases"

    id: int | None = Field(default=None, primary_key=True)
    expert_id: int = Field(foreign_key="experts.id", index=True)
    alias: str = Field(index=True)
    lang: str = Field(default="zh")


# ---------------------------------------------------------------------------
# Events  (论坛/采访/keynote 这类可复用 anchor)
# ---------------------------------------------------------------------------
class Event(SQLModel, table=True):
    __tablename__ = "events"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    kind: EventKind = Field(default=EventKind.other)
    host: str | None = None
    date: datetime | None = None
    url: str | None = None
    description: str | None = None
    embedding: list[float] | None = embedding_field()
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Sources  (媒体/平台元数据)
# ---------------------------------------------------------------------------
class Source(SQLModel, table=True):
    __tablename__ = "sources"

    id: int | None = Field(default=None, primary_key=True)
    domain: str = Field(index=True, unique=True)
    name: str
    kind: SourceKind = Field(default=SourceKind.other)
    lang: str = Field(default="zh")
    reliability_score: float = Field(default=0.5)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Viewpoints  (7 元组核心)
# ---------------------------------------------------------------------------
class Viewpoint(SQLModel, table=True):
    __tablename__ = "viewpoints"

    id: int | None = Field(default=None, primary_key=True)
    expert_id: int = Field(foreign_key="experts.id", index=True)
    event_id: int | None = Field(default=None, foreign_key="events.id", index=True)
    source_id: int | None = Field(default=None, foreign_key="sources.id", index=True)

    # ---- 7-tuple ----
    claim_who_role: str | None = None
    claim_when: datetime | None = Field(default=None, index=True)
    claim_where: str | None = None
    claim_what: str = ""
    claim_quote: str | None = None
    claim_medium: str | None = None
    claim_source_url: str | None = None
    claim_why_context: str | None = None
    # -----------------

    claim_lang: str = Field(default="zh")
    embedding: list[float] | None = embedding_field()
    confidence: float = Field(default=0.5)
    providers_seen: list[str] | None = str_array_field(default=None)
    ingested_at: datetime = Field(default_factory=datetime.utcnow)


class ViewpointTopic(SQLModel, table=True):
    __tablename__ = "viewpoint_topics"

    viewpoint_id: int = Field(foreign_key="viewpoints.id", primary_key=True)
    topic_id: int = Field(foreign_key="topics.id", primary_key=True)
    relevance: float = Field(default=1.0)


# ---------------------------------------------------------------------------
# Skills  (sedimented prompt templates)
# ---------------------------------------------------------------------------
class Skill(SQLModel, table=True):
    __tablename__ = "skills"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    kind: SkillKind = Field(default=SkillKind.search)
    domain: str | None = Field(default=None, index=True)
    prompt_template: str
    success_score: float = Field(default=0.0)
    last_used_at: datetime | None = None
    version: int = Field(default=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Report templates  (用户在 /templates 编辑)
# ---------------------------------------------------------------------------
class ReportTemplate(SQLModel, table=True):
    __tablename__ = "report_templates"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    kind: TemplateKind = Field(default=TemplateKind.md_report)
    prompt_template: str
    jinja_vars: dict | None = json_field(default=None)
    is_default: bool = Field(default=False)
    is_builtin: bool = Field(default=False)
    version: int = Field(default=1)
    description: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Reports  (output container)
# ---------------------------------------------------------------------------
class Report(SQLModel, table=True):
    __tablename__ = "reports"

    id: int | None = Field(default=None, primary_key=True)
    title: str
    kind: ReportKind = Field(default=ReportKind.adhoc)
    focus_topics: list[str] | None = str_array_field(default=None)
    time_range_start: datetime | None = None
    time_range_end: datetime | None = None

    md_template_id: int | None = Field(default=None, foreign_key="report_templates.id")
    outline_template_id: int | None = Field(default=None, foreign_key="report_templates.id")

    providers_enabled: list[str] | None = str_array_field(default=None)
    max_reflection_rounds: int = Field(default=3)
    cost_cap_usd: float = Field(default=10.0)

    status: ReportStatus = Field(default=ReportStatus.pending, index=True)
    error: str | None = None

    md_path: str | None = None
    outline_json_path: str | None = None
    pdf_path: str | None = None

    total_tokens: int = Field(default=0)
    total_cost_usd: float = Field(default=0.0)

    thread_id: str | None = Field(default=None, description="LangGraph thread id for resume")

    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ReportSection(SQLModel, table=True):
    __tablename__ = "report_sections"

    id: int | None = Field(default=None, primary_key=True)
    report_id: int = Field(foreign_key="reports.id", index=True)
    topic_id: int | None = Field(default=None, foreign_key="topics.id")
    cluster_label: str
    cluster_kind: ClusterKind = Field(default=ClusterKind.consensus)
    summary_md: str
    viewpoint_ids: list[int] | None = json_field(default=None)
    order: int = Field(default=0)


# ---------------------------------------------------------------------------
# Agent runs  (per-node observability)
# ---------------------------------------------------------------------------
class AgentRun(SQLModel, table=True):
    __tablename__ = "agent_runs"

    id: int | None = Field(default=None, primary_key=True)
    report_id: int = Field(foreign_key="reports.id", index=True)
    graph_node: str = Field(index=True)
    state_in: dict | None = json_field(default=None)
    state_out: dict | None = json_field(default=None)
    tokens: int = Field(default=0)
    cost_usd: float = Field(default=0.0)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: datetime | None = None
    error: str | None = None


class ProviderCall(SQLModel, table=True):
    __tablename__ = "provider_calls"

    id: int | None = Field(default=None, primary_key=True)
    agent_run_id: int | None = Field(default=None, foreign_key="agent_runs.id", index=True)
    report_id: int | None = Field(default=None, foreign_key="reports.id", index=True)
    provider: str = Field(index=True)
    model: str
    purpose: str = Field(default="search")  # search | extract | analyze | embed
    query: str | None = None
    tokens_input: int = Field(default=0)
    tokens_output: int = Field(default=0)
    cost_usd: float = Field(default=0.0)
    latency_ms: int = Field(default=0)
    success: bool = Field(default=True)
    error: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# Re-export ordered list for Alembic autogenerate ordering
__all__ = [
    "ProviderCredential",
    "Topic",
    "Expert",
    "ExpertAlias",
    "Event",
    "Source",
    "Viewpoint",
    "ViewpointTopic",
    "Skill",
    "ReportTemplate",
    "Report",
    "ReportSection",
    "AgentRun",
    "ProviderCall",
]
