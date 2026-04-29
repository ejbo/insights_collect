"""Gemini provider — google-genai with Google Search grounding."""

from __future__ import annotations

import time
from urllib.parse import urlparse

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

_PRICE = {"gemini-2.5-pro": (1.25, 5.0), "gemini-2.5-flash": (0.075, 0.3)}


def _cost(model: str, i: int, o: int) -> float:
    r = _PRICE.get(model, (1.25, 5.0))
    return i / 1_000_000 * r[0] + o / 1_000_000 * r[1]


def _domain(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return (urlparse(url).hostname or "").lower().lstrip("www.")
    except Exception:  # noqa: BLE001
        return None


class GeminiProvider(SearchProvider):
    name = "gemini"
    default_search_model = "gemini-2.5-flash"
    default_reasoning_model = "gemini-2.5-pro"

    def __init__(self, api_key: str = "", base_url: str | None = None, default_model: str | None = None):
        super().__init__(api_key, base_url, default_model)
        self._client = None
        if api_key:
            from google import genai
            self._client = genai.Client(api_key=api_key)

    def _ensure(self):
        if self._client is None:
            raise ProviderUnavailable("Gemini API key missing")
        return self._client

    async def search(
        self,
        query: str,
        time_window: TimeRange,
        lang: str = "zh",
        max_results: int = 10,
    ) -> SearchResult:
        client = self._ensure()
        from google.genai import types
        model = self.default_search_model
        prompt = (
            f"Find recent expert viewpoints between {time_window.start.date()} and "
            f"{time_window.end.date()}. {'用中文' if lang == 'zh' else 'In English'}.\n\n"
            f"Query: {query}"
        )
        t0 = time.perf_counter()
        try:
            resp = await client.aio.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                ),
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

        text = resp.text or ""
        snippets: list[RawSnippet] = []
        gm = getattr(resp.candidates[0], "grounding_metadata", None) if resp.candidates else None
        if gm:
            for chunk in (getattr(gm, "grounding_chunks", []) or []):
                w = getattr(chunk, "web", None)
                if w:
                    url = getattr(w, "uri", None)
                    title = getattr(w, "title", None)
                    snippets.append(RawSnippet(
                        title=title, snippet=text[:400], url=url,
                        source_domain=_domain(url), provider=self.name, lang=lang,
                    ))
        if not snippets and text:
            snippets.append(RawSnippet(snippet=text, provider=self.name, lang=lang))

        usage = getattr(resp, "usage_metadata", None)
        in_t = getattr(usage, "prompt_token_count", 0) if usage else 0
        out_t = getattr(usage, "candidates_token_count", 0) if usage else 0
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
        from google.genai import types
        model = model or self.default_reasoning_model
        full = f"{prompt}\n\n---\nContext:\n{context}" if context else prompt
        t0 = time.perf_counter()
        try:
            resp = await client.aio.models.generate_content(
                model=model,
                contents=full,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                ),
            )
        except Exception as e:  # noqa: BLE001
            raise ProviderUnavailable(f"Gemini extract failed: {e}") from e
        try:
            data = schema.model_validate_json(resp.text)
        except Exception as e:  # noqa: BLE001
            raise ProviderUnavailable(f"Gemini returned invalid schema: {e}") from e
        usage = getattr(resp, "usage_metadata", None)
        in_t = getattr(usage, "prompt_token_count", 0) if usage else 0
        out_t = getattr(usage, "candidates_token_count", 0) if usage else 0
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
        resp = await client.aio.models.generate_content(model=model, contents=full)
        usage = getattr(resp, "usage_metadata", None)
        in_t = getattr(usage, "prompt_token_count", 0) if usage else 0
        out_t = getattr(usage, "candidates_token_count", 0) if usage else 0
        return AnalyzeResult(
            text=resp.text or "",
            trace=ProviderCallTrace(
                provider=self.name, model=model, purpose="analyze", query=prompt[:200],
                tokens_input=in_t, tokens_output=out_t, cost_usd=_cost(model, in_t, out_t),
                latency_ms=int((time.perf_counter() - t0) * 1000),
            ),
        )
