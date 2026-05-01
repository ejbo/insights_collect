"""Anthropic Claude — Opus 4.7 with web_search + web_fetch + citations.

Compliant with Opus 4.7 requirements:
  - Adaptive thinking ONLY (no `budget_tokens`; that field returns 400 on 4.7)
  - `thinking.display = "summarized"` so reasoning is visible (default is "omitted")
  - No `temperature` / `top_p` / `top_k` (those fields return 400 on 4.7)
  - Streaming for every call (avoids long-request timeouts)
  - `output_config.effort` for thinking depth + token spend control
  - Optional `output_config.task_budget` (beta header `task-budgets-2026-03-13`)
  - Server-side `web_search_20260209` + `web_fetch_20260209` tools
  - Citations + raw search results returned in `trace.extra` for DB persistence

Pricing for cost estimation (USD per 1M tokens):
  claude-opus-4-7   : $5 input / $25 output
  claude-sonnet-4-6 : $3 input / $15 output
  claude-haiku-4-5  : $1 input / $5 output
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

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


_PRICE: dict[str, tuple[float, float]] = {
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-opus-4-5": (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


def _price_for(model: str) -> tuple[float, float]:
    if model in _PRICE:
        return _PRICE[model]
    for k, v in _PRICE.items():
        if model.startswith(k):
            return v
    return (5.0, 25.0)


def _cost(model: str, in_t: int, out_t: int) -> float:
    rates = _price_for(model)
    return (in_t / 1_000_000) * rates[0] + (out_t / 1_000_000) * rates[1]


# No read deadline — Anthropic web_search + thinking can take a long time and
# the user prefers a finished answer over a premature cut-off. Streaming keeps
# the socket healthy regardless of duration.
_HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)


# ---------------------------------------------------------------------------
# User-customizable Claude options
# ---------------------------------------------------------------------------
@dataclass
class ClaudeOptions:
    """Per-run user-configurable Claude knobs.

    Defaults are "中规中矩": balanced quality + cost.
    """
    effort: str = "low"                        # low | medium | high | xhigh | max
    max_uses: int = 1                          # max web_search invocations
    max_fetches: int = 0                       # max web_fetch invocations (kept for back-compat — UI no longer exposes it)
    task_budget_tokens: int | None = None      # beta task-budgets; min 20_000
    thinking_display: str = "summarized"       # omitted | summarized
    enable_web_search: bool = True
    enable_web_fetch: bool = False             # forced off — UI no longer exposes the toggle
    allowed_domains: list[str] | None = None
    blocked_domains: list[str] | None = None
    user_location_country: str | None = None
    model: str | None = None                   # override default search model

    @classmethod
    def from_dict(cls, d: dict | None) -> ClaudeOptions:
        if not d:
            return cls()
        try:
            return cls(
                effort=d.get("effort") or "low",
                max_uses=int(d.get("max_uses") or 1),
                max_fetches=0,
                task_budget_tokens=(int(d["task_budget_tokens"])
                                    if d.get("task_budget_tokens") else None),
                thinking_display=d.get("thinking_display") or "summarized",
                enable_web_search=bool(d.get("enable_web_search", True)),
                enable_web_fetch=False,  # ignore any incoming truthy — feature retired in UI
                allowed_domains=d.get("allowed_domains") or None,
                blocked_domains=d.get("blocked_domains") or None,
                user_location_country=d.get("user_location_country") or None,
                model=d.get("model") or None,
            )
        except Exception:  # noqa: BLE001
            return cls()


_VALID_EFFORT = {"low", "medium", "high", "xhigh", "max"}


class AnthropicProvider(SearchProvider):
    name = "anthropic"
    default_search_model = "claude-opus-4-7"
    default_reasoning_model = "claude-opus-4-7"

    def __init__(self, api_key: str = "", base_url: str | None = None,
                 default_model: str | None = None):
        super().__init__(api_key, base_url, default_model)
        self._client = (
            AsyncAnthropic(api_key=api_key, base_url=base_url, timeout=_HTTP_TIMEOUT)
            if api_key else None
        )

    def _ensure(self) -> AsyncAnthropic:
        if self._client is None:
            raise ProviderUnavailable("Anthropic API key missing")
        return self._client

    # ------------------------------------------------------------------
    # quick_validate — sub-second key check via models.list
    # ------------------------------------------------------------------
    async def quick_validate(self) -> ProviderCallTrace:
        client = self._ensure()
        t0 = time.perf_counter()
        page = await client.models.list(limit=3)
        latency = int((time.perf_counter() - t0) * 1000)
        ids = [m.id for m in page.data][:3]
        return ProviderCallTrace(
            provider=self.name, model="(models.list)", purpose="health",
            success=True, latency_ms=latency,
            extra={"sent": "GET /v1/models?limit=3", "got": ", ".join(ids)},
        )

    # ------------------------------------------------------------------
    # Builders
    # ------------------------------------------------------------------
    def _build_tools(self, opts: ClaudeOptions, time_window: TimeRange) -> list[dict]:
        tools: list[dict] = []
        if opts.enable_web_search:
            ws: dict[str, Any] = {
                "type": "web_search_20260209",
                "name": "web_search",
                "max_uses": opts.max_uses,
            }
            if opts.allowed_domains:
                ws["allowed_domains"] = opts.allowed_domains
            if opts.blocked_domains:
                ws["blocked_domains"] = opts.blocked_domains
            if opts.user_location_country:
                ws["user_location"] = {
                    "type": "approximate",
                    "country": opts.user_location_country,
                }
            tools.append(ws)
        if opts.enable_web_fetch:
            wf: dict[str, Any] = {
                "type": "web_fetch_20260209",
                "name": "web_fetch",
                "max_uses": opts.max_fetches,
            }
            if opts.allowed_domains:
                wf["allowed_domains"] = opts.allowed_domains
            if opts.blocked_domains:
                wf["blocked_domains"] = opts.blocked_domains
            tools.append(wf)
        return tools

    def _build_output_config(self, opts: ClaudeOptions) -> dict:
        effort = opts.effort if opts.effort in _VALID_EFFORT else "high"
        cfg: dict[str, Any] = {"effort": effort}
        if opts.task_budget_tokens and opts.task_budget_tokens >= 20_000:
            cfg["task_budget"] = {"type": "tokens", "total": int(opts.task_budget_tokens)}
        return cfg

    def _betas_for(self, opts: ClaudeOptions) -> list[str]:
        betas: list[str] = []
        if opts.task_budget_tokens and opts.task_budget_tokens >= 20_000:
            betas.append("task-budgets-2026-03-13")
        return betas

    def _system_prompt(self, time_window: TimeRange, lang: str) -> str:
        if lang == "zh":
            return (
                f"你是一名研究助手。请使用 web_search 工具检索 "
                f"{time_window.start.date()} 至 {time_window.end.date()} 期间针对所给主题的"
                f"专家公开发言。如果初步搜索结果信息不足或链接需要展开原文，请用 web_fetch "
                f"抓取该 URL 的完整内容。\n\n"
                f"对每条值得记录的观点，请明确给出：\n"
                f"- 专家姓名 + 角色 / 单位\n"
                f"- 时间（具体日期）\n"
                f"- 场合 / 论坛 / 节目\n"
                f"- 直接引用（原话）以及该专家的核心观点摘要\n"
                f"- 来源 URL（必须能直接打开）\n\n"
                f"请尽量挖出多种立场（看好 / 质疑 / 中立观察），"
                f"既包括知名大咖，也包括在该主题上有特定影响力但不广为人知的专家。"
            )
        return (
            f"You are a research assistant. Use the web_search tool to find expert "
            f"viewpoints on the given topics between {time_window.start.date()} "
            f"and {time_window.end.date()}. If results are thin or you need full "
            f"context, use web_fetch on specific URLs to retrieve the full page.\n\n"
            f"For each viewpoint worth recording, provide:\n"
            f"- Expert name + role / affiliation\n"
            f"- Date (specific)\n"
            f"- Venue / forum / interview show\n"
            f"- Direct quote AND a summary of the claim\n"
            f"- Source URL (must be openable)\n\n"
            f"Surface multiple stances (bullish / skeptical / neutral) and include "
            f"both well-known voices and topic-specific authorities who may be less "
            f"famous overall."
        )

    # ------------------------------------------------------------------
    # search — primary entrypoint, uses web_search + web_fetch
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
        opts = ClaudeOptions.from_dict(options)
        model = opts.model or self.default_search_model
        sys = self._system_prompt(time_window, lang)
        tools = self._build_tools(opts, time_window)
        output_config = self._build_output_config(opts)
        betas = self._betas_for(opts)

        msg_kwargs: dict[str, Any] = dict(
            model=model,
            max_tokens=16000,
            system=sys,
            tools=tools,
            output_config=output_config,
            thinking={"type": "adaptive", "display": opts.thinking_display},
            messages=[{"role": "user", "content": query}],
        )

        t0 = time.perf_counter()
        try:
            if betas:
                async with client.beta.messages.stream(betas=betas, **msg_kwargs) as stream:
                    resp = await stream.get_final_message()
            else:
                async with client.messages.stream(**msg_kwargs) as stream:
                    resp = await stream.get_final_message()
        except Exception as e:  # noqa: BLE001
            return SearchResult(
                snippets=[],
                trace=ProviderCallTrace(
                    provider=self.name, model=model, purpose="search", query=query,
                    success=False, error=str(e)[:400],
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                ),
            )

        snippets, search_results, citations, thinking_summary, final_text = \
            _parse_response(resp, lang=lang, query=query)

        usage = getattr(resp, "usage", None)
        in_t = getattr(usage, "input_tokens", 0) if usage else 0
        out_t = getattr(usage, "output_tokens", 0) if usage else 0
        cache_read = getattr(usage, "cache_read_input_tokens", 0) if usage else 0
        cache_write = getattr(usage, "cache_creation_input_tokens", 0) if usage else 0
        # `usage.server_tool_use` reports the *actual* number of times Claude
        # invoked each server-side tool. We surface it so the UI can show the
        # real count alongside the configured cap (`max_uses`).
        st_use = getattr(usage, "server_tool_use", None) if usage else None
        actual_searches = getattr(st_use, "web_search_requests", None) if st_use else None
        actual_fetches = getattr(st_use, "web_fetch_requests", None) if st_use else None
        cost = _cost(model, in_t, out_t)

        # No artificial cap — `max_uses` is the only knob the user has, and
        # whatever Anthropic returns from each tool invocation is what we
        # persist. The previous truncation made changing max_uses look like a
        # no-op in the UI's hit count.
        return SearchResult(
            snippets=snippets,
            trace=ProviderCallTrace(
                provider=self.name, model=model, purpose="search", query=query,
                tokens_input=in_t, tokens_output=out_t, cost_usd=cost,
                latency_ms=int((time.perf_counter() - t0) * 1000),
                extra={
                    "search_results": search_results,
                    "citations": citations,
                    "thinking_summary": thinking_summary,
                    "final_text": final_text[:2000] if final_text else None,
                    "effort": opts.effort,
                    "max_uses": opts.max_uses,
                    "max_fetches": opts.max_fetches,
                    "task_budget": opts.task_budget_tokens,
                    "cache_read_tokens": cache_read,
                    "cache_creation_tokens": cache_write,
                    "stop_reason": getattr(resp, "stop_reason", None),
                    "tool_usage": {
                        "web_search_actual": actual_searches,
                        "web_fetch_actual": actual_fetches,
                    },
                },
            ),
        )

    # ------------------------------------------------------------------
    # structured_extract — used by Planner / ExpertDiscoverer / etc.
    # ------------------------------------------------------------------
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
        tool_name = schema.__name__
        tool_schema = schema.model_json_schema()

        t0 = time.perf_counter()
        try:
            async with client.messages.stream(
                model=model,
                max_tokens=16000,
                output_config={"effort": "high"},
                thinking={"type": "adaptive", "display": "omitted"},
                tools=[{
                    "name": tool_name,
                    "description": f"Emit a {tool_name} object.",
                    "input_schema": tool_schema,
                }],
                tool_choice={"type": "tool", "name": tool_name},
                messages=[{"role": "user", "content": full}],
            ) as stream:
                resp = await stream.get_final_message()
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

    # ------------------------------------------------------------------
    # analyze — used by ClusterAnalyzer, summary writers
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
        async with client.messages.stream(
            model=model,
            max_tokens=8000,
            output_config={"effort": "high"},
            thinking={"type": "adaptive", "display": "omitted"},
            messages=[{"role": "user", "content": full}],
        ) as stream:
            resp = await stream.get_final_message()
        text = "".join(
            getattr(b, "text", "") for b in resp.content
            if getattr(b, "type", None) == "text"
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


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------
def _domain(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return (urlparse(url).hostname or "").lower().lstrip("www.")
    except Exception:  # noqa: BLE001
        return None


def _parse_response(
    resp: Any, lang: str, query: str,
) -> tuple[list[RawSnippet], list[dict], list[dict], str, str]:
    """Walk content blocks; extract snippets, search_results, citations, thinking summary, final text.

    Returns:
        snippets:        For downstream LangGraph nodes (RawSnippet objects)
        search_results:  Raw search hit metadata for SearchResult DB rows
        citations:       Inline citation blocks (cited_text + url + title)
        thinking_summary: Concatenated `thinking` blocks text (if display=summarized)
        final_text:      The final text answer Claude wrote
    """
    snippets: list[RawSnippet] = []
    search_results: list[dict] = []
    citations: list[dict] = []
    thinking_chunks: list[str] = []
    text_chunks: list[str] = []
    last_query: str | None = None

    for block in getattr(resp, "content", []):
        btype = getattr(block, "type", None)

        if btype == "thinking":
            t = getattr(block, "thinking", "") or ""
            if t:
                thinking_chunks.append(t)

        elif btype == "server_tool_use":
            # The agent invoked web_search or web_fetch
            inp = getattr(block, "input", None)
            if isinstance(inp, dict):
                last_query = inp.get("query") or inp.get("url") or last_query

        elif btype == "web_search_tool_result":
            for item in (getattr(block, "content", []) or []):
                title = getattr(item, "title", None)
                url = getattr(item, "url", None)
                page_age = getattr(item, "page_age", None)
                domain = _domain(url)
                search_results.append({
                    "query": last_query,
                    "title": title,
                    "url": url,
                    "source_domain": domain,
                    "page_age": page_age,
                    "kind": "web_search",
                })
                snippets.append(RawSnippet(
                    title=title,
                    snippet=(title or ""),
                    url=url,
                    source_domain=domain,
                    provider="anthropic",
                    lang=lang,
                ))

        elif btype == "web_fetch_tool_result":
            content = getattr(block, "content", None)
            url = None
            text = ""
            if content:
                items = content if isinstance(content, list) else [content]
                for c in items:
                    if isinstance(c, dict):
                        text += c.get("text", "") or ""
                        url = c.get("url") or url
                    else:
                        text += getattr(c, "text", "") or ""
                        url = getattr(c, "url", None) or url
            domain = _domain(url)
            search_results.append({
                "query": last_query,
                "title": None,
                "url": url,
                "source_domain": domain,
                "page_age": None,
                "snippet": (text[:600] if text else None),
                "kind": "web_fetch",
            })
            if text:
                snippets.append(RawSnippet(
                    title=None, snippet=text[:1500], url=url,
                    source_domain=domain, provider="anthropic", lang=lang,
                ))

        elif btype == "text":
            text = getattr(block, "text", "") or ""
            text_chunks.append(text)
            cits = getattr(block, "citations", None) or []
            for c in cits:
                citations.append({
                    "type": getattr(c, "type", None),
                    "cited_text": getattr(c, "cited_text", None),
                    "url": getattr(c, "url", None),
                    "title": getattr(c, "title", None),
                })

    # Always at least one snippet — use the final text if no search results
    if not snippets and text_chunks:
        snippets.append(RawSnippet(
            snippet="\n".join(text_chunks)[:1500],
            provider="anthropic", lang=lang,
        ))

    return (
        snippets,
        search_results,
        citations,
        "\n\n".join(thinking_chunks)[:4000],
        "".join(text_chunks),
    )
