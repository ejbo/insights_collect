"""API request/response shapes (where they differ from DB models)."""

from datetime import datetime

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
class CreateReportRequest(BaseModel):
    title: str
    focus_topics: list[str] = Field(min_length=1)
    time_range_start: datetime = Field(description="时间窗起始（ISO 日期或日期时间）")
    time_range_end: datetime = Field(description="时间窗结束（ISO 日期或日期时间）")
    md_template_id: int | None = None
    outline_template_id: int | None = None
    providers_enabled: list[str] | None = None
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
    has_key: bool
    base_url: str | None
    default_model: str | None
    enabled: bool
    last_tested_at: datetime | None
    test_status: str | None
    test_message: str | None


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
