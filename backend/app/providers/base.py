"""Provider abstraction — all 6 search/LLM adapters implement this contract.

Credentials are loaded by `credentials_loader` (DB-first, .env fallback). Adapters never
read settings directly; they receive `api_key` / `base_url` / `default_model` at construction
or per-call.

Each call also returns a `ProviderCallTrace` so the orchestrator can persist token/cost.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel

from app.schemas.llm import RawSnippet


@dataclass
class TimeRange:
    start: datetime
    end: datetime

    @classmethod
    def last_n_days(cls, n: int) -> TimeRange:
        end = datetime.utcnow()
        return cls(start=end - timedelta(days=n), end=end)


@dataclass
class ProviderCallTrace:
    provider: str
    model: str
    purpose: str  # search | extract | analyze | embed
    query: str | None = None
    tokens_input: int = 0
    tokens_output: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    success: bool = True
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResult:
    snippets: list[RawSnippet]
    trace: ProviderCallTrace


@dataclass
class ExtractResult:
    data: BaseModel
    trace: ProviderCallTrace


@dataclass
class AnalyzeResult:
    text: str
    trace: ProviderCallTrace


class SearchProvider(ABC):
    """Common interface every provider implements.

    Some providers (e.g., Perplexity) excel at `search`; others (Claude/OpenAI) at `extract`/`analyze`.
    Implementations may raise `ProviderUnavailable` or return empty + success=False trace
    when the API key is missing/invalid; orchestrator gracefully skips that provider.
    """

    name: str = "base"
    default_search_model: str = ""
    default_reasoning_model: str = ""

    def __init__(
        self,
        api_key: str = "",
        base_url: str | None = None,
        default_model: str | None = None,
    ):
        self.api_key = api_key
        self.base_url = base_url
        if default_model:
            self.default_search_model = default_model

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    @abstractmethod
    async def search(
        self,
        query: str,
        time_window: TimeRange,
        lang: str = "zh",
        max_results: int = 10,
        options: dict | None = None,
        **kwargs: Any,
    ) -> SearchResult:
        ...

    @abstractmethod
    async def structured_extract(
        self,
        prompt: str,
        schema: type[BaseModel],
        context: str | None = None,
        model: str | None = None,
    ) -> ExtractResult:
        ...

    @abstractmethod
    async def analyze(
        self,
        prompt: str,
        context: list[str] | None = None,
        model: str | None = None,
    ) -> AnalyzeResult:
        ...

    async def health_check(self) -> ProviderCallTrace:
        """Cheap key-validity check (no LLM tokens). Default: minimal analyze.
        Providers with a list-models endpoint should override `quick_validate`.
        """
        try:
            return await self.quick_validate()
        except Exception as e:  # noqa: BLE001
            return ProviderCallTrace(
                provider=self.name, model=self.default_search_model, purpose="health",
                success=False, error=str(e)[:300],
            )

    async def quick_validate(self) -> ProviderCallTrace:
        """Default: tiny analyze call. Subclasses override with /v1/models GET
        for sub-second key validation.
        """
        import time as _t
        t0 = _t.perf_counter()
        res = await self.analyze("hi")
        return ProviderCallTrace(
            provider=self.name, model=res.trace.model, purpose="health",
            tokens_input=res.trace.tokens_input, tokens_output=res.trace.tokens_output,
            cost_usd=res.trace.cost_usd, latency_ms=res.trace.latency_ms,
            success=True,
            extra={"sent": "analyze('hi')", "got": (res.text or "")[:80]},
        )


class ProviderUnavailable(Exception):
    pass
