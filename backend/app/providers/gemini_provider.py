"""Google Gemini provider — gemini-3.1-pro-preview with Google Search grounding.

Aligned with https://ai.google.dev/gemini-api/docs/google-search

For Gemini 2.5+ (and the 3.x preview line), enabling search is just
`tools=[{"google_search": {}}]` with no parameters — no dynamic_retrieval_config.
The model decides when to ground; the response carries `grounding_metadata` with:
  - web_search_queries[]   — actual queries Gemini fired
  - grounding_chunks[].web — {uri, title} for each cited source
  - grounding_supports[]   — segment-to-chunk mapping for inline citations
  - search_entry_point     — Google's required attribution HTML widget

User-customizable via GeminiOptions:
  - model            — override default `gemini-3.1-pro-preview`
  - thinking_budget  — Gemini 2.5+ thinking config (-1 dynamic, 0 off, 128-32768)
  - temperature      — 0.0-2.0 (Gemini still supports sampling, unlike Opus 4.7)
  - max_output_tokens
  - enable_search    — toggle the google_search tool
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
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


# Pricing (USD per 1M tokens). Preview models priced same as 2.5-pro until GA.
_PRICE: dict[str, tuple[float, float]] = {
    "gemini-3.1-pro-preview": (1.5, 6.0),
    "gemini-2.5-pro": (1.25, 5.0),
    "gemini-2.5-flash": (0.075, 0.3),
}


def _price_for(model: str) -> tuple[float, float]:
    if model in _PRICE:
        return _PRICE[model]
    for k, v in _PRICE.items():
        if model.startswith(k):
            return v
    return (1.25, 5.0)


def _cost(model: str, in_t: int, out_t: int) -> float:
    rates = _price_for(model)
    return (in_t / 1_000_000) * rates[0] + (out_t / 1_000_000) * rates[1]


# ---------------------------------------------------------------------------
# User-customizable Gemini options
# ---------------------------------------------------------------------------
@dataclass
class GeminiOptions:
    model: str | None = None
    # -1 = dynamic (model decides), 0 = thinking off, 128–32768 = fixed budget
    thinking_budget: int = -1
    temperature: float | None = None      # 0.0 - 2.0
    max_output_tokens: int = 8192
    enable_search: bool = True
    user_location_country: str | None = None
    # Soft cap on how many distinct google_search calls Gemini fires per turn.
    # The SDK has no hard knob for this; we inject the limit into the prompt
    # so the model self-restricts. Defaults match the user's "fewer searches"
    # request — well below Gemini's typical 8–12 per call.
    max_search_queries: int = 3
    # Soft cap on how many grounding chunks to keep when persisting SearchHits.
    # Useful when google_search returns a long tail of low-relevance citations.
    max_grounding_chunks: int = 8

    @classmethod
    def from_dict(cls, d: dict | None) -> GeminiOptions:
        if not d:
            return cls()
        try:
            return cls(
                model=d.get("model") or None,
                thinking_budget=int(d.get("thinking_budget", -1)),
                temperature=(float(d["temperature"])
                             if d.get("temperature") is not None else None),
                max_output_tokens=int(d.get("max_output_tokens") or 8192),
                enable_search=bool(d.get("enable_search", True)),
                user_location_country=d.get("user_location_country") or None,
                max_search_queries=int(d.get("max_search_queries") or 3),
                max_grounding_chunks=int(d.get("max_grounding_chunks") or 8),
            )
        except Exception:  # noqa: BLE001
            return cls()


def _domain(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return (urlparse(url).hostname or "").lower().lstrip("www.")
    except Exception:  # noqa: BLE001
        return None


class GeminiProvider(SearchProvider):
    name = "gemini"
    default_search_model = "gemini-3.1-pro-preview"
    default_reasoning_model = "gemini-3.1-pro-preview"

    def __init__(self, api_key: str = "", base_url: str | None = None,
                 default_model: str | None = None):
        super().__init__(api_key, base_url, default_model)
        self._client = None
        if api_key:
            from google import genai
            self._client = genai.Client(api_key=api_key)

    def _ensure(self):
        if self._client is None:
            raise ProviderUnavailable("Gemini API key missing")
        return self._client

    # ------------------------------------------------------------------
    # quick_validate — list models is fast and free
    # ------------------------------------------------------------------
    async def quick_validate(self) -> ProviderCallTrace:
        client = self._ensure()
        t0 = time.perf_counter()
        names: list[str] = []
        try:
            async for m in await client.aio.models.list():
                names.append(getattr(m, "name", str(m)))
                if len(names) >= 3:
                    break
        except Exception as e:  # noqa: BLE001
            return ProviderCallTrace(
                provider=self.name, model="-", purpose="health",
                success=False, error=str(e)[:300],
                latency_ms=int((time.perf_counter() - t0) * 1000),
            )
        latency = int((time.perf_counter() - t0) * 1000)
        return ProviderCallTrace(
            provider=self.name, model="(models.list)", purpose="health",
            success=True, latency_ms=latency,
            extra={"sent": "GET /v1beta/models", "got": ", ".join(names)},
        )

    # ------------------------------------------------------------------
    # search — primary entrypoint with Google Search grounding
    # ------------------------------------------------------------------
    async def search(
        self,
        query: str,
        time_window: TimeRange,
        lang: str = "zh",
        max_results: int = 10,
        options: dict | None = None,
        **_: Any,
    ) -> SearchResult:
        client = self._ensure()
        from google.genai import types

        opts = GeminiOptions.from_dict(options)
        model = opts.model or self.default_search_model

        # Build prompt with time-window instruction baked in
        prompt = self._search_prompt(query, time_window, lang, opts.max_search_queries)

        # Build tools — google_search grounding (Gemini 2.5+ form, no params)
        tools: list[Any] = []
        if opts.enable_search:
            tools.append(types.Tool(google_search=types.GoogleSearch()))

        # Build generation config
        cfg_kwargs: dict[str, Any] = {
            "max_output_tokens": opts.max_output_tokens,
        }
        if tools:
            cfg_kwargs["tools"] = tools
        if opts.temperature is not None:
            cfg_kwargs["temperature"] = opts.temperature

        # Thinking config (Gemini 2.5+; preview models inherit this)
        try:
            tc = types.ThinkingConfig(thinking_budget=opts.thinking_budget)
            cfg_kwargs["thinking_config"] = tc
        except Exception:  # noqa: BLE001
            # Older SDK fallback — silently skip
            pass

        config = types.GenerateContentConfig(**cfg_kwargs)

        t0 = time.perf_counter()
        try:
            resp = await client.aio.models.generate_content(
                model=model,
                contents=prompt,
                config=config,
            )
        except Exception as e:  # noqa: BLE001
            return SearchResult(
                snippets=[],
                trace=ProviderCallTrace(
                    provider=self.name, model=model, purpose="search", query=query,
                    success=False, error=str(e)[:400],
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                ),
            )

        snippets, search_results, citations, web_queries = _parse_response(
            resp, lang=lang, query=query,
            max_chunks=opts.max_grounding_chunks,
        )

        usage = getattr(resp, "usage_metadata", None)
        in_t = (getattr(usage, "prompt_token_count", 0) or 0) if usage else 0
        out_t = (getattr(usage, "candidates_token_count", 0) or 0) if usage else 0
        thinking_t = (getattr(usage, "thoughts_token_count", 0) or 0) if usage else 0
        cost = _cost(model, in_t, out_t + thinking_t)

        final_text = "".join(
            getattr(p, "text", "") or ""
            for cand in (getattr(resp, "candidates", []) or [])
            for p in (getattr(getattr(cand, "content", None), "parts", []) or [])
        )

        return SearchResult(
            snippets=snippets[:max_results] if max_results else snippets,
            trace=ProviderCallTrace(
                provider=self.name, model=model, purpose="search", query=query,
                tokens_input=in_t, tokens_output=out_t + thinking_t, cost_usd=cost,
                latency_ms=int((time.perf_counter() - t0) * 1000),
                extra={
                    "search_results": search_results,
                    "citations": citations,
                    "web_search_queries": web_queries,
                    "thinking_tokens": thinking_t,
                    "thinking_budget": opts.thinking_budget,
                    "temperature": opts.temperature,
                    "enable_search": opts.enable_search,
                    "max_search_queries": opts.max_search_queries,
                    "max_grounding_chunks": opts.max_grounding_chunks,
                    "final_text": final_text[:2000] if final_text else None,
                    "model": model,
                },
            ),
        )

    # ------------------------------------------------------------------
    # structured_extract — JSON schema output, no grounding
    # ------------------------------------------------------------------
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
            data = schema.model_validate_json(resp.text or "{}")
        except Exception as e:  # noqa: BLE001
            raise ProviderUnavailable(f"Gemini returned invalid schema: {e}") from e
        usage = getattr(resp, "usage_metadata", None)
        in_t = (getattr(usage, "prompt_token_count", 0) or 0) if usage else 0
        out_t = (getattr(usage, "candidates_token_count", 0) or 0) if usage else 0
        return ExtractResult(
            data=data,
            trace=ProviderCallTrace(
                provider=self.name, model=model, purpose="extract", query=prompt[:200],
                tokens_input=in_t, tokens_output=out_t, cost_usd=_cost(model, in_t, out_t),
                latency_ms=int((time.perf_counter() - t0) * 1000),
            ),
        )

    # ------------------------------------------------------------------
    # analyze — plain text reasoning
    # ------------------------------------------------------------------
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
        in_t = (getattr(usage, "prompt_token_count", 0) or 0) if usage else 0
        out_t = (getattr(usage, "candidates_token_count", 0) or 0) if usage else 0
        return AnalyzeResult(
            text=resp.text or "",
            trace=ProviderCallTrace(
                provider=self.name, model=model, purpose="analyze", query=prompt[:200],
                tokens_input=in_t, tokens_output=out_t, cost_usd=_cost(model, in_t, out_t),
                latency_ms=int((time.perf_counter() - t0) * 1000),
            ),
        )

    # ------------------------------------------------------------------
    def _search_prompt(self, query: str, tw: TimeRange, lang: str, max_queries: int) -> str:
        # Imperative phrasing — the google_search tool is opt-in for the
        # model on every turn; without an explicit instruction it sometimes
        # answers from training data and grounding_metadata comes back empty.
        # `max_queries` is a soft cap — Gemini's google_search has no API-side
        # quota, so we instruct the model to self-restrict.
        if lang == "zh":
            return (
                f"**必须** 调用 google_search 工具，针对下方主题在 "
                f"{tw.start.date()} 至 {tw.end.date()} 期间收集专家发声。"
                f"**最多发起 {max_queries} 次 google_search 调用**——优先精准、"
                f"高相关的搜索语，而不是大量泛化检索。**不要凭记忆回答**；"
                f"如果搜索没找到，宁可返回少量结果，也不要捏造。\n\n"
                f"主题：{query}\n\n"
                f"对每条值得记录的观点，请明确给出：\n"
                f"- 专家姓名 + 角色 / 单位\n"
                f"- 时间（具体日期）\n"
                f"- 场合 / 论坛 / 节目\n"
                f"- 直接引用（原话）以及核心观点摘要\n"
                f"- 来源 URL（必须能直接打开）\n\n"
                f"挖多种立场：知名大咖 + 长尾权威。"
            )
        return (
            f"**You MUST call the google_search tool** to gather expert "
            f"viewpoints on the topic below, between {tw.start.date()} and "
            f"{tw.end.date()}. **Issue at most {max_queries} google_search "
            f"calls**; prefer precise, high-signal queries over many broad "
            f"ones. **Do not answer from memory** — if search returns nothing, "
            f"return fewer results rather than fabricating.\n\n"
            f"Topic: {query}\n\n"
            f"For each viewpoint worth recording, provide:\n"
            f"- Expert name + role / affiliation\n"
            f"- Date (specific)\n"
            f"- Venue / forum / interview show\n"
            f"- Direct quote AND a summary of the claim\n"
            f"- Source URL (must be openable)\n\n"
            f"Surface multiple stances; include well-known voices and "
            f"topic-specific authorities."
        )


# ---------------------------------------------------------------------------
# grounding_metadata parser
# ---------------------------------------------------------------------------
def _is_url_like(s: str | None) -> bool:
    """Gemini sometimes hands us the URL itself in the title slot — useless to
    surface to the user. Spot it so we can fall back to a better label."""
    if not s:
        return True
    s = s.strip()
    return s.startswith(("http://", "https://", "www.")) or s.endswith((".com", ".org", ".net"))


def _resolve_title(raw_title: str | None, url: str | None, fallback_text: str | None) -> str | None:
    """Pick the best human-readable title: the model-supplied one if it isn't
    just the URL; else the cited text (truncated); else the URL's domain."""
    if raw_title and not _is_url_like(raw_title):
        return raw_title.strip()
    if fallback_text and fallback_text.strip():
        text = fallback_text.strip().splitlines()[0].strip()
        return text[:140] if text else None
    return _domain(url)


def _parse_response(
    resp: Any, lang: str, query: str, max_chunks: int = 8,
) -> tuple[list[RawSnippet], list[dict], list[dict], list[str]]:
    """Walk Gemini response → (snippets, search_results, citations, web_queries).

    grounding_metadata structure (Gemini 2.5+):
      candidates[0].grounding_metadata = {
        web_search_queries: [str, ...],
        grounding_chunks:   [{web: {uri, title}}, ...],
        grounding_supports: [{segment: {start_index, end_index, text}, grounding_chunk_indices: [int, ...]}, ...],
        search_entry_point: {rendered_content: "..."},
      }
    """
    snippets: list[RawSnippet] = []
    search_results: list[dict] = []
    citations: list[dict] = []
    web_queries: list[str] = []

    candidates = getattr(resp, "candidates", None) or []
    if not candidates:
        return snippets, search_results, citations, web_queries

    cand = candidates[0]
    gm = getattr(cand, "grounding_metadata", None)

    # Final text concatenated from parts
    full_text = ""
    for p in (getattr(getattr(cand, "content", None), "parts", []) or []):
        full_text += getattr(p, "text", "") or ""

    if not gm:
        # No grounding — just return the text as a single snippet
        if full_text:
            snippets.append(RawSnippet(
                snippet=full_text[:1500], provider="gemini", lang=lang,
            ))
        return snippets, search_results, citations, web_queries

    # web_search_queries
    web_queries = list(getattr(gm, "web_search_queries", []) or [])

    # First pass: collect chunk URIs and raw titles. We intentionally defer
    # SearchHit/RawSnippet emission until after grounding_supports gives us a
    # cited_text we can use as a fallback title.
    raw_chunks = getattr(gm, "grounding_chunks", []) or []
    chunk_meta: list[dict] = []
    for ch in raw_chunks:
        web = getattr(ch, "web", None)
        if web is None:
            chunk_meta.append({})
            continue
        uri = getattr(web, "uri", None)
        title = getattr(web, "title", None)
        chunk_meta.append({
            "url": uri,
            "raw_title": title,
            "domain": _domain(uri),
            "cited_texts": [],  # filled by the supports pass
        })

    # grounding_supports → cited_text per chunk + citation entries
    for sup in (getattr(gm, "grounding_supports", []) or []):
        seg = getattr(sup, "segment", None)
        cited_text = getattr(seg, "text", None) if seg else None
        idxs = list(getattr(sup, "grounding_chunk_indices", []) or [])
        for i in idxs:
            if 0 <= i < len(chunk_meta):
                meta = chunk_meta[i]
                if not meta:
                    continue
                if cited_text:
                    meta["cited_texts"].append(cited_text)
                citations.append({
                    "type": "google_search_result",
                    "cited_text": cited_text,
                    "url": meta.get("url"),
                    "title": meta.get("raw_title"),
                })

    # Second pass: emit SearchHits / RawSnippets with resolved titles.
    # Apply the chunk cap here (after collecting cited_texts so the cap
    # doesn't drop the most-cited chunks unfairly).
    for meta in chunk_meta[:max_chunks]:
        if not meta:
            continue
        first_cite = meta["cited_texts"][0] if meta["cited_texts"] else None
        title = _resolve_title(meta.get("raw_title"), meta.get("url"), first_cite)
        snippet_text = (
            first_cite or title or meta.get("raw_title") or ""
        )
        search_results.append({
            "query": web_queries[0] if web_queries else query,
            "title": title,
            "url": meta.get("url"),
            "source_domain": meta.get("domain"),
            "page_age": None,
            "kind": "web_search",
        })
        snippets.append(RawSnippet(
            title=title,
            snippet=snippet_text[:1500],
            url=meta.get("url"),
            source_domain=meta.get("domain"),
            provider="gemini",
            lang=lang,
        ))

    # If there were no grounding chunks but there is text, still emit it
    if not snippets and full_text:
        snippets.append(RawSnippet(
            snippet=full_text[:1500], provider="gemini", lang=lang,
        ))

    return snippets, search_results, citations, web_queries
