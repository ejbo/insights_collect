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
    "gpt-5.5": (5.0, 20.0),
    "gpt-5": (5.0, 20.0),
    "gpt-5-mini": (0.5, 2.0),
}


def _cost(model: str, i: int, o: int) -> float:
    if model in _PRICE:
        return i / 1_000_000 * _PRICE[model][0] + o / 1_000_000 * _PRICE[model][1]
    for k, (in_p, out_p) in _PRICE.items():
        if model.startswith(k):
            return i / 1_000_000 * in_p + o / 1_000_000 * out_p
    return i / 1_000_000 * 5.0 + o / 1_000_000 * 20.0


def _domain(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return (urlparse(url).hostname or "").lower().lstrip("www.")
    except Exception:  # noqa: BLE001
        return None


class OpenAIProvider(SearchProvider):
    name = "openai"
    default_search_model = "gpt-5.5"
    default_reasoning_model = "gpt-5.5"

    def __init__(self, api_key: str = "", base_url: str | None = None, default_model: str | None = None):
        super().__init__(api_key, base_url, default_model)
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url) if api_key else None

    def _ensure(self) -> AsyncOpenAI:
        if self._client is None:
            raise ProviderUnavailable("OpenAI API key missing")
        return self._client

    async def quick_validate(self) -> ProviderCallTrace:
        client = self._ensure()
        t0 = time.perf_counter()
        page = await client.models.list()
        latency = int((time.perf_counter() - t0) * 1000)
        ids = [m.id for m in page.data][:3]
        return ProviderCallTrace(
            provider=self.name, model="(models.list)", purpose="health",
            success=True, latency_ms=latency,
            extra={"sent": "GET /v1/models", "got": ", ".join(ids) + f" (+{max(0,len(page.data)-3)} more)"},
        )

    async def search(
        self,
        query: str,
        time_window: TimeRange,
        lang: str = "zh",
        max_results: int = 10,
        options: dict | None = None,
        **_: object,
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
        search_results: list[dict] = []
        seen_urls: set[str] = set()
        final_text_chunks: list[str] = []

        for item in getattr(resp, "output", []) or []:
            item_type = getattr(item, "type", None)

            # 1) The model invoked the web_search tool — surfaces the actual
            # query it ran and the source list it pulled.
            if item_type in ("web_search_call", "web_search_tool_call"):
                action = getattr(item, "action", None)
                tool_query = getattr(action, "query", None) or query
                # Different SDK versions: `sources` on the action, or `results`
                # on the item itself.
                src_list = (
                    getattr(action, "sources", None)
                    or getattr(item, "results", None)
                    or []
                )
                for s in src_list:
                    url = getattr(s, "url", None) or (s.get("url") if isinstance(s, dict) else None)
                    title = (
                        getattr(s, "title", None)
                        or (s.get("title") if isinstance(s, dict) else None)
                    )
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    search_results.append({
                        "query": tool_query,
                        "title": title,
                        "url": url,
                        "source_domain": _domain(url),
                        "page_age": None,
                        "kind": "web_search",
                    })
                    snippets.append(RawSnippet(
                        title=title, snippet=(title or "")[:400], url=url,
                        source_domain=_domain(url), provider=self.name, lang=lang,
                    ))
                continue

            # 2) Message items — the assistant's text + url_citation annotations
            for content in getattr(item, "content", []) or []:
                txt = getattr(content, "text", "") or ""
                if txt:
                    final_text_chunks.append(txt)
                annotations = getattr(content, "annotations", []) or []
                for ann in annotations:
                    ann_type = getattr(ann, "type", None)
                    if ann_type and ann_type not in ("url_citation", "citation"):
                        continue
                    url = getattr(ann, "url", None)
                    title = getattr(ann, "title", None)
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    search_results.append({
                        "query": query,
                        "title": title,
                        "url": url,
                        "source_domain": _domain(url),
                        "page_age": None,
                        "kind": "web_search",
                    })
                    snippets.append(RawSnippet(
                        title=title, snippet=txt[:400] or (title or ""),
                        url=url, source_domain=_domain(url),
                        provider=self.name, lang=lang,
                    ))

        # If grounding produced no citations but we still got a final text,
        # keep one snippet so downstream nodes have something to chew on.
        if not snippets and final_text_chunks:
            snippets.append(RawSnippet(
                snippet="\n".join(final_text_chunks)[:1500],
                provider=self.name, lang=lang,
            ))

        usage = getattr(resp, "usage", None)
        in_t = getattr(usage, "input_tokens", 0) if usage else 0
        out_t = getattr(usage, "output_tokens", 0) if usage else 0
        final_text = "\n".join(final_text_chunks)
        return SearchResult(
            snippets=snippets[:max_results] if max_results else snippets,
            trace=ProviderCallTrace(
                provider=self.name, model=model, purpose="search", query=query,
                tokens_input=in_t, tokens_output=out_t, cost_usd=_cost(model, in_t, out_t),
                latency_ms=int((time.perf_counter() - t0) * 1000),
                extra={
                    "search_results": search_results,
                    "final_text": final_text[:2000] if final_text else None,
                    "model": model,
                },
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
