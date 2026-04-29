"""OpenAI provider — Responses API with web_search tool + structured outputs."""

from __future__ import annotations

import time
from urllib.parse import urlparse

from openai import AsyncOpenAI
from pydantic import BaseModel

from app.providers.base import (
    AnalyzeResult,
    ExtractResult,
    ProviderCallTrace,
    ProviderUnavailable,
    SearchProvider,
    SearchResult,
    TimeRange,
)
from app.schemas.llm import RawSnippet


_PRICE = {
    "gpt-5": (5.0, 20.0),
    "gpt-5-mini": (0.5, 2.0),
}


def _cost(model: str, i: int, o: int) -> float:
    r = _PRICE.get(model, (5.0, 20.0))
    return i / 1_000_000 * r[0] + o / 1_000_000 * r[1]


def _domain(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return (urlparse(url).hostname or "").lower().lstrip("www.")
    except Exception:  # noqa: BLE001
        return None


class OpenAIProvider(SearchProvider):
    name = "openai"
    default_search_model = "gpt-5-mini"
    default_reasoning_model = "gpt-5"

    def __init__(self, api_key: str = "", base_url: str | None = None, default_model: str | None = None):
        super().__init__(api_key, base_url, default_model)
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url) if api_key else None

    def _ensure(self) -> AsyncOpenAI:
        if self._client is None:
            raise ProviderUnavailable("OpenAI API key missing")
        return self._client

    async def search(
        self,
        query: str,
        time_window: TimeRange,
        lang: str = "zh",
        max_results: int = 10,
    ) -> SearchResult:
        client = self._ensure()
        model = self.default_search_model
        instr = (
            f"Find recent expert viewpoints between {time_window.start.date()} and "
            f"{time_window.end.date()}. Provide title, url, source, date when known. "
            f"Output {'中文' if lang == 'zh' else 'English'}."
        )
        t0 = time.perf_counter()
        try:
            resp = await client.responses.create(
                model=model,
                input=f"{instr}\n\nQuery: {query}",
                tools=[{"type": "web_search"}],
            )
        except Exception as e:  # noqa: BLE001
            return SearchResult(
                snippets=[],
                trace=ProviderCallTrace(
                    provider=self.name, model=model, purpose="search", query=query,
                    success=False, error=str(e),
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                ),
            )

        snippets: list[RawSnippet] = []
        # Extract citations from output_text + annotations
        for item in getattr(resp, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                txt = getattr(content, "text", "")
                annotations = getattr(content, "annotations", []) or []
                for ann in annotations:
                    url = getattr(ann, "url", None)
                    title = getattr(ann, "title", None)
                    snippets.append(RawSnippet(
                        title=title, snippet=txt[:400], url=url,
                        source_domain=_domain(url), provider=self.name, lang=lang,
                    ))
                if not annotations and txt:
                    snippets.append(RawSnippet(snippet=txt, provider=self.name, lang=lang))

        usage = getattr(resp, "usage", None)
        in_t = getattr(usage, "input_tokens", 0) if usage else 0
        out_t = getattr(usage, "output_tokens", 0) if usage else 0
        return SearchResult(
            snippets=snippets[:max_results],
            trace=ProviderCallTrace(
                provider=self.name, model=model, purpose="search", query=query,
                tokens_input=in_t, tokens_output=out_t, cost_usd=_cost(model, in_t, out_t),
                latency_ms=int((time.perf_counter() - t0) * 1000),
            ),
        )

    async def structured_extract(
        self,
        prompt: str,
        schema: type[BaseModel],
        context: str | None = None,
        model: str | None = None,
    ) -> ExtractResult:
        client = self._ensure()
        model = model or self.default_reasoning_model
        full = f"{prompt}\n\n---\nContext:\n{context}" if context else prompt
        t0 = time.perf_counter()
        try:
            resp = await client.responses.parse(
                model=model,
                input=full,
                text_format=schema,
            )
        except Exception as e:  # noqa: BLE001
            raise ProviderUnavailable(f"OpenAI extract failed: {e}") from e

        data = resp.output_parsed
        usage = getattr(resp, "usage", None)
        in_t = getattr(usage, "input_tokens", 0) if usage else 0
        out_t = getattr(usage, "output_tokens", 0) if usage else 0
        return ExtractResult(
            data=data,
            trace=ProviderCallTrace(
                provider=self.name, model=model, purpose="extract", query=prompt[:200],
                tokens_input=in_t, tokens_output=out_t, cost_usd=_cost(model, in_t, out_t),
                latency_ms=int((time.perf_counter() - t0) * 1000),
            ),
        )

    async def analyze(
        self,
        prompt: str,
        context: list[str] | None = None,
        model: str | None = None,
    ) -> AnalyzeResult:
        client = self._ensure()
        model = model or self.default_reasoning_model
        joined = ("\n\n---\n".join(context)) if context else ""
        full = f"{prompt}\n\n---\nContext:\n{joined}" if joined else prompt
        t0 = time.perf_counter()
        resp = await client.responses.create(model=model, input=full)
        text = getattr(resp, "output_text", "") or ""
        usage = getattr(resp, "usage", None)
        in_t = getattr(usage, "input_tokens", 0) if usage else 0
        out_t = getattr(usage, "output_tokens", 0) if usage else 0
        return AnalyzeResult(
            text=text,
            trace=ProviderCallTrace(
                provider=self.name, model=model, purpose="analyze", query=prompt[:200],
                tokens_input=in_t, tokens_output=out_t, cost_usd=_cost(model, in_t, out_t),
                latency_ms=int((time.perf_counter() - t0) * 1000),
            ),
        )
