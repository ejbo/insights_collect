"""OpenAI-compatible provider — used by Qwen (DashScope) and DeepSeek.

Both expose OpenAI-compatible REST. Subclasses fix `name`, `default_search_model`, `_BASE`.

Qwen overrides `search()` to use DashScope's Responses API + native `web_search`
tool (per https://www.alibabacloud.com/help/en/model-studio/web-search) so we
get back structured citations instead of a free-form text dump.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
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


def _domain(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return (urlparse(url).hostname or "").lower().lstrip("www.")
    except Exception:  # noqa: BLE001
        return None


class _OpenAICompatProvider(SearchProvider):
    name = "openai-compat"
    default_search_model = ""
    default_reasoning_model = ""
    _BASE = ""
    _PRICE: dict[str, tuple[float, float]] = {}
    _SUPPORTS_NATIVE_SEARCH = False  # toggled by subclasses if API has built-in search tool

    def __init__(self, api_key: str = "", base_url: str | None = None, default_model: str | None = None):
        super().__init__(api_key, base_url, default_model)
        self._base = base_url or self._BASE

    def _cost(self, model: str, i: int, o: int) -> float:
        r = self._PRICE.get(model, (1.0, 3.0))
        return i / 1_000_000 * r[0] + o / 1_000_000 * r[1]

    async def _post(self, path: str, payload: dict) -> dict:
        if not self.api_key:
            raise ProviderUnavailable(f"{self.name} API key missing")
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(f"{self._base}{path}", json=payload, headers=headers)
            r.raise_for_status()
            return r.json()

    async def quick_validate(self) -> ProviderCallTrace:
        if not self.api_key:
            raise ProviderUnavailable(f"{self.name} API key missing")
        headers = {"Authorization": f"Bearer {self.api_key}"}
        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{self._base}/models", headers=headers)
        latency = int((time.perf_counter() - t0) * 1000)
        if r.status_code != 200:
            return ProviderCallTrace(
                provider=self.name, model="-", purpose="health",
                success=False, latency_ms=latency,
                error=f"HTTP {r.status_code}: {r.text[:200]}",
            )
        try:
            data = r.json()
            ids = [m.get("id", "") for m in (data.get("data") or [])][:3]
        except Exception:  # noqa: BLE001
            ids = []
        return ProviderCallTrace(
            provider=self.name, model="(models.list)", purpose="health",
            success=True, latency_ms=latency,
            extra={"sent": f"GET {self._base}/models", "got": ", ".join(ids) or "ok"},
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
        model = self.default_search_model
        prompt = (
            f"任务：检索 {time_window.start.date()} 到 {time_window.end.date()} "
            f"期间，关于 “{query}” 的近期专家观点。请尽量列出：\n"
            f"- 专家姓名 + 角色\n- 时间\n- 场合 / 论坛 / 采访栏目\n- 原话或观点摘要\n"
            f"- 来源链接（必填）\n"
            f"以条目化文本输出。\n"
            f"{'优先中文媒体源（如央视、央广、财新、上海财大、中国发展高层论坛、新华社等）' if lang == 'zh' else 'Prefer English-language sources.'}"
        )
        t0 = time.perf_counter()
        payload = {"model": model, "messages": [{"role": "user", "content": prompt}]}
        if self._SUPPORTS_NATIVE_SEARCH:
            payload["enable_search"] = True
        try:
            data = await self._post("/chat/completions", payload)
        except Exception as e:  # noqa: BLE001
            return SearchResult(
                snippets=[],
                trace=ProviderCallTrace(
                    provider=self.name, model=model, purpose="search", query=query,
                    success=False, error=str(e),
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                ),
            )

        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        usage = data.get("usage") or {}
        in_t = usage.get("prompt_tokens", 0)
        out_t = usage.get("completion_tokens", 0)
        snippets = [RawSnippet(snippet=text, provider=self.name, lang=lang)] if text else []
        return SearchResult(
            snippets=snippets[:max_results],
            trace=ProviderCallTrace(
                provider=self.name, model=model, purpose="search", query=query,
                tokens_input=in_t, tokens_output=out_t,
                cost_usd=self._cost(model, in_t, out_t),
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
        model = model or self.default_reasoning_model
        full = f"{prompt}\n\n---\nContext:\n{context}" if context else prompt
        full += (
            "\n\n请仅返回符合下方 JSON Schema 的 JSON 对象，不要任何额外文字："
            f"\n```json\n{schema.model_json_schema()}\n```"
        )
        t0 = time.perf_counter()
        data = await self._post("/chat/completions", {
            "model": model,
            "messages": [{"role": "user", "content": full}],
            "response_format": {"type": "json_object"},
        })
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        try:
            obj = schema.model_validate_json(text)
        except Exception as e:  # noqa: BLE001
            raise ProviderUnavailable(f"{self.name} returned invalid schema: {e}") from e
        usage = data.get("usage") or {}
        in_t = usage.get("prompt_tokens", 0)
        out_t = usage.get("completion_tokens", 0)
        return ExtractResult(
            data=obj,
            trace=ProviderCallTrace(
                provider=self.name, model=model, purpose="extract", query=prompt[:200],
                tokens_input=in_t, tokens_output=out_t,
                cost_usd=self._cost(model, in_t, out_t),
                latency_ms=int((time.perf_counter() - t0) * 1000),
            ),
        )

    async def analyze(
        self,
        prompt: str,
        context: list[str] | None = None,
        model: str | None = None,
    ) -> AnalyzeResult:
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
                tokens_input=in_t, tokens_output=out_t,
                cost_usd=self._cost(model, in_t, out_t),
                latency_ms=int((time.perf_counter() - t0) * 1000),
            ),
        )


@dataclass
class QwenOptions:
    """Per-run knobs for Qwen's web_search.

    See: https://www.alibabacloud.com/help/en/model-studio/web-search
    """
    model: str | None = None
    enable_search: bool = True
    enable_thinking: bool = True
    # 'agent' = web search only; 'agent_max' = adds web scraping (more depth,
    # higher cost, requires thinking mode for qwen3-max snapshots).
    search_strategy: str = "agent"
    max_output_tokens: int = 8192

    @classmethod
    def from_dict(cls, d: dict | None) -> QwenOptions:
        if not d:
            return cls()
        try:
            return cls(
                model=d.get("model") or None,
                enable_search=bool(d.get("enable_search", True)),
                enable_thinking=bool(d.get("enable_thinking", True)),
                search_strategy=str(d.get("search_strategy") or "agent"),
                max_output_tokens=int(d.get("max_output_tokens") or 8192),
            )
        except Exception:  # noqa: BLE001
            return cls()


class QwenProvider(_OpenAICompatProvider):
    """阿里云 DashScope OpenAI-compatible 网关.

    `search()` 改用 Responses API + web_search 工具 (DashScope 原生),
    其它方法 (structured_extract / analyze / quick_validate) 仍走父类的
    Chat Completions 实现。
    """
    name = "qwen"
    # Default to user-requested qwen3.6-plus (rolling). User can override per
    # report via QwenOptions.model. Older snapshots remain priced below.
    default_search_model = "qwen3.6-plus"
    default_reasoning_model = "qwen3.6-plus"
    _BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    # Pricing (USD per 1M tokens). qwen3.6-plus assumed at the qwen-plus tier
    # until Alibaba publishes a separate sheet; qwen3-max kept for users who
    # explicitly switch to the heavyweight tier.
    _PRICE = {
        "qwen3.6-plus": (0.4, 1.2),
        "qwen3.5-plus": (0.4, 1.2),
        "qwen3-max":    (3.0, 12.0),
        "qwen3-max-2026-01-23": (3.0, 12.0),
        "qwen-max":     (2.4, 9.6),
        "qwen-plus":    (0.8, 2.0),
    }
    _SUPPORTS_NATIVE_SEARCH = True

    async def search(
        self,
        query: str,
        time_window: TimeRange,
        lang: str = "zh",
        max_results: int = 10,
        options: dict | None = None,
        **_: Any,
    ) -> SearchResult:
        if not self.api_key:
            raise ProviderUnavailable("Qwen API key missing")

        opts = QwenOptions.from_dict(options)
        model = opts.model or self.default_search_model
        prompt = self._search_prompt(query, time_window, lang)

        # DashScope's OpenAI-Compatible Chat Completions API accepts non-OpenAI
        # top-level fields like `enable_search`, `enable_thinking`,
        # `search_strategy`. (See: alibabacloud.com/help/en/model-studio/web-search)
        # We hit /chat/completions because /responses is only enabled for a
        # narrow set of snapshots (qwen3.5, qwen3-max snapshots) and silently
        # returns empty on others — that's the "✓ but 0 hits / 0 tokens"
        # smoke-test signature the user reported.
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": opts.max_output_tokens,
            "enable_thinking": opts.enable_thinking,
        }
        if opts.enable_search:
            payload["enable_search"] = True
            # search_strategy is only honored in agent mode; harmless otherwise.
            payload["search_options"] = {
                "search_strategy": opts.search_strategy,
                "enable_source": True,
                "enable_citation": True,
                "citation_format": "[ref_<number>]",
            }

        t0 = time.perf_counter()
        try:
            data = await self._post("/chat/completions", payload)
        except httpx.HTTPStatusError as e:  # noqa: BLE001
            return SearchResult(
                snippets=[],
                trace=ProviderCallTrace(
                    provider=self.name, model=model, purpose="search", query=query,
                    success=False,
                    error=f"HTTP {e.response.status_code}: {e.response.text[:300]}",
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                ),
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

        latency = int((time.perf_counter() - t0) * 1000)
        snippets, search_results, citations, final_text = _parse_qwen_chat_payload(
            data, lang=lang, query=query,
        )

        usage = data.get("usage") or {}
        in_t = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
        out_t = usage.get("completion_tokens") or usage.get("output_tokens") or 0
        thinking_t = (usage.get("reasoning_tokens")
                      or (usage.get("output_tokens_details") or {}).get("reasoning_tokens")
                      or 0)
        cost = self._cost(model, in_t, out_t + thinking_t)

        # If the call truly returned nothing useful, surface that as failure
        # so the smoke test doesn't show "✓ 0 conditions / 0 tokens" — that
        # almost always means a model / region mismatch (e.g. qwen3.5-plus
        # via /responses on a US-region endpoint that doesn't expose it).
        if not snippets and not final_text and in_t == 0 and out_t == 0:
            return SearchResult(
                snippets=[],
                trace=ProviderCallTrace(
                    provider=self.name, model=model, purpose="search", query=query,
                    success=False,
                    error="empty response — check that the model supports your region's "
                          "DashScope endpoint and that enable_search is allowed.",
                    latency_ms=latency,
                    extra={"raw_keys": list(data.keys())[:10]},
                ),
            )

        return SearchResult(
            snippets=snippets[:max_results] if max_results else snippets,
            trace=ProviderCallTrace(
                provider=self.name, model=model, purpose="search", query=query,
                tokens_input=in_t, tokens_output=out_t + thinking_t, cost_usd=cost,
                latency_ms=latency, success=True,
                extra={
                    "search_results": search_results,
                    "citations": citations,
                    "enable_search": opts.enable_search,
                    "enable_thinking": opts.enable_thinking,
                    "search_strategy": opts.search_strategy,
                    "reasoning_tokens": thinking_t,
                    "final_text": (final_text or "")[:2000],
                    "model": model,
                },
            ),
        )

    @staticmethod
    def _search_prompt(query: str, tw: TimeRange, lang: str) -> str:
        if lang == "zh":
            return (
                f"使用 web_search 工具检索 {tw.start.date()} 至 {tw.end.date()} "
                f"期间关于以下主题的专家观点：\n\n{query}\n\n"
                "对每条值得记录的观点请明确给出：\n"
                "- 专家姓名 + 角色 / 单位\n"
                "- 时间（具体日期）\n"
                "- 场合 / 论坛 / 节目\n"
                "- 直接引用（原话）以及核心观点摘要\n"
                "- 来源 URL（必须能直接打开）\n\n"
                "优先中文媒体源（如央视、央广、财新、上海财大、新华社、"
                "中国发展高层论坛等），但也可以包含英文权威源。"
            )
        return (
            f"Use the web_search tool to find expert viewpoints on the topic "
            f"below, between {tw.start.date()} and {tw.end.date()}.\n\n"
            f"Topic: {query}\n\n"
            "For each viewpoint worth recording, provide:\n"
            "- Expert name + role / affiliation\n"
            "- Date (specific)\n"
            "- Venue / forum / show\n"
            "- Direct quote AND a summary of the claim\n"
            "- Source URL (must be openable)\n"
        )


def _parse_qwen_chat_payload(
    data: dict, lang: str, query: str,
) -> tuple[list[RawSnippet], list[dict], list[dict], str]:
    """DashScope's OpenAI-Compatible Chat Completions response with
    enable_search includes search-result metadata in a few possible places:

      - choices[0].message.search_results           (v0/v1 enable_search)
      - choices[0].message.tool_calls               (when web_search tool used)
      - top-level data["search_info"]["search_results"]  (newer snapshots)

    We try each in order and dedup by URL.
    """
    choices = data.get("choices") or []
    final_text = ""
    raw_results: list[dict] = []

    if choices:
        msg = (choices[0] or {}).get("message") or {}
        final_text = (msg.get("content") or "") if isinstance(msg, dict) else ""

        # 1. message.search_results (canonical for enable_search)
        for sr in msg.get("search_results") or []:
            if isinstance(sr, dict):
                raw_results.append(sr)

        # 2. tool_calls (if model invoked web_search via tools)
        for tc in msg.get("tool_calls") or []:
            args = (tc.get("function") or {}).get("arguments")
            if isinstance(args, str):
                try:
                    import json as _json
                    parsed = _json.loads(args)
                    for sr in parsed.get("search_results") or []:
                        if isinstance(sr, dict):
                            raw_results.append(sr)
                except Exception:  # noqa: BLE001
                    pass

    # 3. top-level search_info (newer DashScope shape)
    si = (data.get("search_info") or {}).get("search_results")
    if isinstance(si, list):
        for sr in si:
            if isinstance(sr, dict):
                raw_results.append(sr)

    seen: set[str] = set()
    search_results: list[dict] = []
    for sr in raw_results:
        url = sr.get("url") or sr.get("link")
        if not url or url in seen:
            continue
        seen.add(url)
        search_results.append({
            "query": query,
            "title": sr.get("title") or sr.get("site_name"),
            "url": url,
            "source_domain": _domain(url),
            "page_age": sr.get("publish_time") or sr.get("date"),
            "kind": "web_search",
            "snippet": sr.get("snippet") or sr.get("description") or sr.get("summary"),
        })

    snippets: list[RawSnippet] = [
        RawSnippet(
            title=h.get("title"),
            snippet=(h.get("snippet") or h.get("title") or "")[:1500] or "(qwen result)",
            url=h.get("url"),
            source_domain=h.get("source_domain"),
            provider="qwen",
            lang=lang,
        )
        for h in search_results
    ]
    if not snippets and final_text:
        snippets.append(RawSnippet(snippet=final_text[:1500], provider="qwen", lang=lang))

    citations = [
        {"url": h["url"], "title": h.get("title"), "cited_text": h.get("snippet")}
        for h in search_results
    ]
    return snippets, search_results, citations, final_text


class DeepSeekProvider(_OpenAICompatProvider):
    name = "deepseek"
    default_search_model = "deepseek-chat"
    default_reasoning_model = "deepseek-reasoner"
    _BASE = "https://api.deepseek.com/v1"
    _PRICE = {"deepseek-chat": (0.27, 1.1), "deepseek-reasoner": (0.55, 2.19)}
    _SUPPORTS_NATIVE_SEARCH = False  # DeepSeek 暂无原生 web_search，仅做 extract/analyze
