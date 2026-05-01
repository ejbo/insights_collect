"""API request/response shapes (where they differ from DB models)."""

from datetime import datetime

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
class ClaudeOptions(BaseModel):
    """User-customizable Claude (Anthropic) options for a report run."""
    effort: str = Field(default="high", description="low | medium | high | xhigh | max")
    # Anthropic API has no published hard cap on max_uses; we allow up to 50 here.
    max_uses: int = Field(default=10, ge=1, le=50, description="max web_search invocations")
    max_fetches: int = Field(default=5, ge=0, le=50, description="max web_fetch invocations")
    task_budget_tokens: int | None = Field(
        default=None, description="If set (>=20000), enables beta task-budgets")
    enable_web_search: bool = True
    enable_web_fetch: bool = True
    allowed_domains: list[str] | None = None
    blocked_domains: list[str] | None = None
    user_location_country: str | None = None
    model: str | None = None


class GrokOptions(BaseModel):
    """User-customizable Grok x_search options. Drives the dual-direction
    (event ↔ people) mining strategy on grok-4.20-reasoning."""
    model: str | None = Field(default=None, description="Default: grok-4.20-reasoning")
    allowed_x_handles: list[str] | None = Field(
        default=None,
        description="Pin search to up to 10 X handles (mutually exclusive with excluded_x_handles)",
    )
    excluded_x_handles: list[str] | None = Field(
        default=None, description="Exclude up to 10 X handles",
    )
    enable_image_understanding: bool = Field(
        default=True, description="Let grok read images attached to posts",
    )
    enable_video_understanding: bool = Field(
        default=True, description="Let grok read videos attached to posts (via SERVER_SIDE_TOOL_VIEW_X_VIDEO)",
    )
    enable_dual_pass: bool = Field(
        default=True,
        description="Run a second 'people-driven' pass after the event pass",
    )
    max_candidate_handles: int = Field(
        default=8, ge=1, le=10,
        description="Max handles carried from pass-1 into pass-2 allowed_x_handles",
    )


class GeminiOptions(BaseModel):
    """User-customizable Gemini options. See https://ai.google.dev/gemini-api/docs/google-search."""
    model: str | None = Field(default=None, description="Default: gemini-3.1-pro-preview")
    thinking_budget: int = Field(
        default=-1,
        description="-1 = dynamic (model decides), 0 = thinking off, 128-32768 = fixed budget",
    )
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_output_tokens: int = Field(default=8192, ge=512, le=32768)
    enable_search: bool = Field(default=True, description="Toggle the google_search tool")
    user_location_country: str | None = None


class MainModelConfig(BaseModel):
    """The single model that handles every node OTHER than multi_search.

    Planner, ExpertDiscoverer, ViewpointExtractor, ClusterAnalyzer, ReportComposer
    all call this model via `structured_extract` / `analyze` (no web_search tools).
    Only multi_search uses the Providers list (with their respective web_search).
    """
    provider: str = Field(default="openai", description="anthropic | openai | gemini | grok | perplexity | qwen | deepseek")
    model: str | None = Field(default=None, description="Model id; null → provider default")


class CreateReportRequest(BaseModel):
    title: str
    focus_topics: list[str] = Field(min_length=1)
    time_range_start: datetime = Field(description="时间窗起始（ISO 日期或日期时间）")
    time_range_end: datetime = Field(description="时间窗结束（ISO 日期或日期时间）")
    md_template_id: int | None = None
    outline_template_id: int | None = None
    providers_enabled: list[str] | None = None
    providers_options: dict[str, dict] | None = Field(
        default=None,
        description="Per-provider knobs, e.g. {\"anthropic\": {\"effort\": \"high\", ...}}",
    )
    main_model: MainModelConfig | None = Field(
        default=None,
        description="Model used for non-search nodes. Default: openai/gpt-5.5.",
    )
    max_reflection_rounds: int = Field(default=3, ge=0, le=5)
    cost_cap_usd: float = Field(default=10.0, gt=0)


class ReportSummary(BaseModel):
    id: int
    title: str
    status: str
    created_at: datetime
    finished_at: datetime | None = None
    total_cost_usd: float = 0.0


# ---------------------------------------------------------------------------
# Provider credentials (settings UI)
# ---------------------------------------------------------------------------
class ProviderCredentialUpdate(BaseModel):
    api_key: str | None = None
    base_url: str | None = None
    default_model: str | None = None
    enabled: bool | None = None


class ProviderCredentialView(BaseModel):
    provider: str
    api_key: str = ""        # plaintext (local-self-use; UI shows it directly)
    has_key: bool
    base_url: str | None
    default_model: str | None
    enabled: bool
    last_tested_at: datetime | None
    test_status: str | None
    test_message: str | None


class BulkProviderUpdate(BaseModel):
    provider: str
    api_key: str | None = None
    base_url: str | None = None
    default_model: str | None = None


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
class TemplateUpsert(BaseModel):
    name: str
    kind: str
    prompt_template: str
    description: str | None = None
    jinja_vars: dict | None = None
    is_default: bool = False


# ---------------------------------------------------------------------------
# Run progress (SSE events)
# ---------------------------------------------------------------------------
class RunEvent(BaseModel):
    report_id: int
    node: str
    stage: str  # start | chunk | finish | error
    message: str | None = None
    payload: dict | None = None
