"""Perplexity Sonar — best-in-class citation transparency."""

from __future__ import annotations

import time
from urllib.parse import urlparse

import httpx
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
    "sonar": (1.0, 1.0),
    "sonar-pro": (3.0, 15.0),
    "sonar-reasoning": (1.0, 5.0),
    "sonar-reasoning-pro": (2.0, 8.0),
}


def _cost(model: str, i: int, o: int) -> float:
    r = _PRICE.get(model, (1.0, 1.0))
    return i / 1_000_000 * r[0] + o / 1_000_000 * r[1]


def _domain(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return (urlparse(url).hostname or "").lower().lstrip("www.")
    except Exception:  # noqa: BLE001
        return None


class PerplexityProvider(SearchProvider):
    name = "perplexity"
    default_search_model = "sonar-pro"
    default_reasoning_model = "sonar-reasoning-pro"
    _BASE = "https://api.perplexity.ai"

    def __init__(self, api_key: str = "", base_url: str | None = None, default_model: str | None = None):
        super().__init__(api_key, base_url, default_model)
        self._base = base_url or self._BASE

    async def _post(self, path: str, payload: dict) -> dict:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(f"{self._base}{path}", json=payload, headers=headers)
            r.raise_for_status()
            return r.json()

    async def search(
        self,
        query: str,
        time_window: TimeRange,
        lang: str = "zh",
        max_results: int = 10,
    ) -> SearchResult:
        if not self.api_key:
            raise ProviderUnavailable("Perplexity API key missing")
        model = self.default_search_model
        sys = (
            f"Find recent expert viewpoints (between {time_window.start.date()} and "
            f"{time_window.end.date()}). Cite sources. {'用中文回答' if lang == 'zh' else 'Answer in English'}."
        )
        t0 = time.perf_counter()
        try:
            data = await self._post("/chat/completions", {
                "model": model,
                "messages": [
                    {"role": "system", "content": sys},
                    {"role": "user", "content": query},
                ],
                "search_recency_filter": "month",
                "return_citations": True,
            })
        except Exception as e:  # noqa: BLE001
            return SearchResult(
                snippets=[],
                trace=ProviderCallTrace(
                    provider=self.name, model=model, purpose="search", query=query,
                    success=False, error=str(e),
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                ),
            )

        choice = (data.get("choices") or [{}])[0]
        content = choice.get("message", {}).get("content", "")
        citations = data.get("citations") or []
        snippets: list[RawSnippet] = []
        for url in citations:
            snippets.append(RawSnippet(
                snippet=content[:400], url=url, source_domain=_domain(url),
                provider=self.name, lang=lang,
            ))
        if not snippets and content:
            snippets.append(RawSnippet(snippet=content, provider=self.name, lang=lang))

        usage = data.get("usage") or {}
        in_t = usage.get("prompt_tokens", 0)
        out_t = usage.get("completion_tokens", 0)
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
        if not self.api_key:
            raise ProviderUnavailable("Perplexity API key missing")
        model = model or self.default_reasoning_model
        full = f"{prompt}\n\n---\nContext:\n{context}" if context else prompt
        t0 = time.perf_counter()
        data = await self._post("/chat/completions", {
            "model": model,
            "messages": [{"role": "user", "content": full}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"schema": schema.model_json_schema()},
            },
        })
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        try:
            obj = schema.model_validate_json(text)
        except Exception as e:  # noqa: BLE001
            raise ProviderUnavailable(f"Perplexity returned invalid schema: {e}") from e
        usage = data.get("usage") or {}
        in_t = usage.get("prompt_tokens", 0)
        out_t = usage.get("completion_tokens", 0)
        return ExtractResult(
            data=obj,
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
        if not self.api_key:
            raise ProviderUnavailable("Perplexity API key missing")
        model = model or self.default_reasoning_model
        joined = ("\n\n---\n".join(context)) if context else ""
        full = f"{prompt}\n\n---\nContext:\n{joined}" if joined else prompt
        t0 = time.perf_counter()
        data = await self._post("/chat/completions", {
            "model": model,
            "messages": [{"role": "user", "content": full}],
        })
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        usage = data.get("usage") or {}
        in_t = usage.get("prompt_tokens", 0)
        out_t = usage.get("completion_tokens", 0)
        return AnalyzeResult(
            text=text,
            trace=ProviderCallTrace(
                provider=self.name, model=model, purpose="analyze", query=prompt[:200],
                tokens_input=in_t, tokens_output=out_t, cost_usd=_cost(model, in_t, out_t),
                latency_ms=int((time.perf_counter() - t0) * 1000),
            ),
        )
