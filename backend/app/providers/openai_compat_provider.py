"""OpenAI-compatible provider — used by Qwen (DashScope) and DeepSeek.

Both expose OpenAI-compatible REST. Subclasses fix `name`, `default_search_model`, `_BASE`.
"""

from __future__ import annotations

import time

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

    async def search(
        self,
        query: str,
        time_window: TimeRange,
        lang: str = "zh",
        max_results: int = 10,
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


class QwenProvider(_OpenAICompatProvider):
    """阿里云 DashScope OpenAI-compatible 网关，含 enable_search."""
    name = "qwen"
    default_search_model = "qwen-max"
    default_reasoning_model = "qwen-max"
    _BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    _PRICE = {"qwen-max": (2.4, 9.6), "qwen-plus": (0.8, 2.0), "qwen3-max": (3.0, 12.0)}
    _SUPPORTS_NATIVE_SEARCH = True


class DeepSeekProvider(_OpenAICompatProvider):
    name = "deepseek"
    default_search_model = "deepseek-chat"
    default_reasoning_model = "deepseek-reasoner"
    _BASE = "https://api.deepseek.com/v1"
    _PRICE = {"deepseek-chat": (0.27, 1.1), "deepseek-reasoner": (0.55, 2.19)}
    _SUPPORTS_NATIVE_SEARCH = False  # DeepSeek 暂无原生 web_search，仅做 extract/analyze
