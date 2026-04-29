"""Anthropic Claude — strongest extractor + native web_search tool.

Note on long requests: Anthropic recommends using *streaming* for messages that may
take a long time (e.g. web_search with several tool calls). We run search() via
`client.messages.stream(...)` to keep the SSE connection alive and avoid
"Request timed out or interrupted" errors. We don't surface chunks; we just await
the final aggregated message.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from anthropic import AsyncAnthropic
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


# Generous per-stage HTTP timeouts. Streaming keeps reads alive in chunks, so we
# set a long *read* but short connect/write to fail fast on real network issues.
_HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)

# Anthropic pricing (USD per 1M tokens) for Opus 4.7 / Sonnet 4.6 — adjust as official rates change.
_PRICE_TABLE = {
    "claude-opus-4-7": (15.0, 75.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5-20251001": (0.8, 4.0),
}


def _cost(model: str, input_t: int, output_t: int) -> float:
    rates = _PRICE_TABLE.get(model, (3.0, 15.0))
    return (input_t / 1_000_000) * rates[0] + (output_t / 1_000_000) * rates[1]


class AnthropicProvider(SearchProvider):
    name = "anthropic"
    default_search_model = "claude-sonnet-4-6"
    default_reasoning_model = "claude-opus-4-7"

    def __init__(self, api_key: str = "", base_url: str | None = None, default_model: str | None = None):
        super().__init__(api_key, base_url, default_model)
        self._client = (
            AsyncAnthropic(api_key=api_key, base_url=base_url, timeout=_HTTP_TIMEOUT)
            if api_key else None
        )

    def _ensure(self) -> AsyncAnthropic:
        if self._client is None:
            raise ProviderUnavailable("Anthropic API key missing")
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
        sys = (
            "You are a research assistant. Use the web_search tool to find recent expert "
            f"viewpoints on the user query. Constrain to dates between "
            f"{time_window.start.date()} and {time_window.end.date()}. Output bullet "
            f"summaries with URL, expert name, source, date when available. Answer in "
            f"{'中文' if lang == 'zh' else 'English'}."
        )
        t0 = time.perf_counter()
        try:
            # Use streaming to keep the SSE connection alive for long web_search
            # tool chains; otherwise Anthropic's API gateway can drop the request
            # after ~30s of silence ("Request timed out or interrupted").
            async with client.messages.stream(
                model=model,
                max_tokens=4096,
                system=sys,
                tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 4}],
                messages=[{"role": "user", "content": query}],
            ) as stream:
                resp = await stream.get_final_message()
        except Exception as e:  # noqa: BLE001
            return SearchResult(
                snippets=[],
                trace=ProviderCallTrace(
                    provider=self.name, model=model, purpose="search", query=query,
                    success=False, error=str(e)[:300],
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                ),
            )

        snippets = _snippets_from_response(resp, provider=self.name, lang=lang)
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
        tool_name = schema.__name__
        tool_schema = schema.model_json_schema()
        msg_content = (
            f"{prompt}\n\n---\nContext:\n{context}" if context else prompt
        )
        t0 = time.perf_counter()
        try:
            resp = await client.messages.create(
                model=model,
                max_tokens=8192,
                tools=[{
                    "name": tool_name,
                    "description": f"Emit a {tool_name} object.",
                    "input_schema": tool_schema,
                }],
                tool_choice={"type": "tool", "name": tool_name},
                messages=[{"role": "user", "content": msg_content}],
            )
        except Exception as e:  # noqa: BLE001
            raise ProviderUnavailable(f"Anthropic extract failed: {e}") from e

        tool_use = next(
            (b for b in resp.content if getattr(b, "type", None) == "tool_use"),
            None,
        )
        if not tool_use:
            raise ProviderUnavailable("Anthropic returned no tool_use block")
        try:
            data = schema.model_validate(tool_use.input)
        except Exception as e:  # noqa: BLE001
            raise ProviderUnavailable(f"Anthropic returned invalid schema: {e}") from e

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
        joined_ctx = ("\n\n---\n".join(context)) if context else ""
        full_prompt = (f"{prompt}\n\n---\nContext:\n{joined_ctx}" if joined_ctx else prompt)
        t0 = time.perf_counter()
        resp = await client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[{"role": "user", "content": full_prompt}],
        )
        text = "".join(
            getattr(b, "text", "") for b in resp.content if getattr(b, "type", None) == "text"
        )
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


def _snippets_from_response(resp: Any, provider: str, lang: str) -> list[RawSnippet]:
    """Extract `web_search_tool_result` blocks from Anthropic response into RawSnippet."""
    out: list[RawSnippet] = []
    for block in getattr(resp, "content", []):
        btype = getattr(block, "type", None)
        if btype == "web_search_tool_result":
            for item in getattr(block, "content", []) or []:
                title = getattr(item, "title", None) or getattr(item, "name", None)
                url = getattr(item, "url", None)
                snippet = getattr(item, "text", None) or getattr(item, "snippet", "") or ""
                domain = _domain(url)
                out.append(RawSnippet(
                    title=title, snippet=snippet, url=url, source_domain=domain,
                    provider=provider, lang=lang,
                ))
        elif btype == "text":
            # Often contains a summary referencing the search results.
            txt = getattr(block, "text", "")
            if txt and len(out) == 0:
                out.append(RawSnippet(snippet=txt, provider=provider, lang=lang))
    return out


def _domain(url: str | None) -> str | None:
    if not url:
        return None
    try:
        from urllib.parse import urlparse
        host = urlparse(url).hostname or ""
        return host.lower().lstrip("www.")
    except Exception:  # noqa: BLE001
        return None
