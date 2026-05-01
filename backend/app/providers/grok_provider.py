"""xAI Grok — X / Twitter content via the Agent Tools API on /v1/responses.

xAI deprecated Live Search in early 2026 ("HTTP 410 — Live search is
deprecated, switch to Agent Tools"). The replacement is the bare Agent Tools
API: hit /v1/responses with `tools=[{"type": "x_search"}]`. The tool object
itself takes no per-call config — no from_date, no x_handles — the model
decides search params internally. So we move time-window + handle filtering
into the *prompt*, where the model still respects them.

Strategy: dual-direction mining in two passes per sub-query.

  Pass 1 — event → people:
      Call /v1/responses with `tools=[{"type":"x_search"}]`. Prompt asks for
      high-impact posts in the time window AND a list of 8-15 X handles.

  Pass 2 — people → event:
      Call /v1/responses again with the same tool, but the prompt now lists
      the candidate handles surfaced in pass 1 and asks Grok to return their
      concrete statements about the topic in-window.

Each pass writes its own ProviderCall + SearchHit rows so the UI shows the
two-step progress separately. Posts whose URL points to /video/ or .jpg etc.
get tagged with `media_type=video|image` for UI badges.

`structured_extract` and `analyze` continue to use /v1/chat/completions and
are unrelated to live search — they're used by non-search nodes.

History: previous version used `/v1/chat/completions + search_parameters`
(Live Search). xAI returned HTTP 410 with the deprecation pointer to
https://docs.x.ai/docs/guides/tools/overview.
"""

from __future__ import annotations

import logging
import re
import time
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

log = logging.getLogger(__name__)

# Pricing assumed equal to grok-4 until xAI publishes a separate sheet.
_PRICE = {
    "grok-4.20-reasoning": (3.0, 15.0),
    "grok-4": (3.0, 15.0),
    "grok-3": (2.0, 10.0),
}

_HANDLE_RE = re.compile(r"(?:^|[^A-Za-z0-9_])@([A-Za-z0-9_]{2,15})\b")
_X_URL_RE = re.compile(r"https?://(?:www\.)?(?:x\.com|twitter\.com)/([^/?#]+)/", re.IGNORECASE)
_X_VIDEO_URL_RE = re.compile(r"x\.com/.+?/(video|i/status/\d+/video)", re.IGNORECASE)


def _cost(m: str, i: int, o: int) -> float:
    r = _PRICE.get(m, (3.0, 15.0))
    return i / 1_000_000 * r[0] + o / 1_000_000 * r[1]


def _domain(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return (urlparse(url).hostname or "").lower().lstrip("www.")
    except Exception:  # noqa: BLE001
        return None


def _media_type_for(url: str | None) -> str:
    if not url:
        return "text"
    if _X_VIDEO_URL_RE.search(url):
        return "video"
    if "/photo/" in url or url.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
        return "image"
    return "text"


class GrokOptions:
    """Per-run knobs for the x_search tool."""

    def __init__(
        self,
        model: str | None = None,
        allowed_x_handles: list[str] | None = None,
        excluded_x_handles: list[str] | None = None,
        enable_image_understanding: bool = True,
        enable_video_understanding: bool = True,
        enable_dual_pass: bool = True,
        max_candidate_handles: int = 8,
    ) -> None:
        self.model = model
        self.allowed_x_handles = allowed_x_handles or None
        self.excluded_x_handles = excluded_x_handles or None
        self.enable_image_understanding = enable_image_understanding
        self.enable_video_understanding = enable_video_understanding
        self.enable_dual_pass = enable_dual_pass
        self.max_candidate_handles = max_candidate_handles

    @classmethod
    def from_dict(cls, d: dict | None) -> GrokOptions:
        if not d:
            return cls()
        try:
            return cls(
                model=d.get("model") or None,
                allowed_x_handles=d.get("allowed_x_handles") or None,
                excluded_x_handles=d.get("excluded_x_handles") or None,
                enable_image_understanding=bool(d.get("enable_image_understanding", True)),
                enable_video_understanding=bool(d.get("enable_video_understanding", True)),
                enable_dual_pass=bool(d.get("enable_dual_pass", True)),
                max_candidate_handles=int(d.get("max_candidate_handles") or 8),
            )
        except Exception:  # noqa: BLE001
            return cls()


class GrokProvider(SearchProvider):
    """xAI: x_search via the OpenAI Responses API at api.x.ai/v1/responses."""

    name = "grok"
    default_search_model = "grok-4.20-reasoning"
    default_reasoning_model = "grok-4.20-reasoning"
    _BASE = "https://api.x.ai/v1"

    def __init__(self, api_key: str = "", base_url: str | None = None, default_model: str | None = None):
        super().__init__(api_key, base_url, default_model)
        self._base = base_url or self._BASE

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------
    async def _post(self, path: str, payload: dict) -> dict:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)) as client:
            r = await client.post(f"{self._base}{path}", json=payload, headers=headers)
            r.raise_for_status()
            return r.json()

    async def quick_validate(self) -> ProviderCallTrace:
        if not self.api_key:
            raise ProviderUnavailable("Grok API key missing")
        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{self._base}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        latency = int((time.perf_counter() - t0) * 1000)
        if r.status_code != 200:
            return ProviderCallTrace(
                provider=self.name, model="-", purpose="health",
                success=False, latency_ms=latency,
                error=f"HTTP {r.status_code}: {r.text[:200]}",
            )
        try:
            ids = [m.get("id", "") for m in (r.json().get("data") or [])][:3]
        except Exception:  # noqa: BLE001
            ids = []
        return ProviderCallTrace(
            provider=self.name, model="(models.list)", purpose="health",
            success=True, latency_ms=latency,
            extra={"sent": f"GET {self._base}/models", "got": ", ".join(ids) or "ok"},
        )

    # ------------------------------------------------------------------
    # search — entrypoint called by multi_search
    # ------------------------------------------------------------------
    async def search(
        self,
        query: str,
        time_window: TimeRange,
        lang: str = "zh",
        max_results: int = 10,
        options: dict | None = None,
        **kwargs: Any,
    ) -> SearchResult:
        if not self.api_key:
            raise ProviderUnavailable("Grok API key missing")

        opts = GrokOptions.from_dict(options)
        report_id = kwargs.get("report_id")
        model = opts.model or self.default_search_model

        # ---- Pass 1: event → people ------------------------------------
        pass1_trace, pass1_snippets, pass1_hits, pass1_text, pass1_handles = await self._call_x_search(
            model=model,
            time_window=time_window,
            lang=lang,
            opts=opts,
            allowed_handles=opts.allowed_x_handles,  # may be None → free search
            user_prompt=self._event_pass_prompt(query, time_window, lang),
            purpose="search:x_event",
            query=query,
        )

        # Persist pass 1 BEFORE running pass 2 so the UI shows progress.
        if report_id is not None:
            try:
                from app.agents.nodes.multi_search import _persist_provider_call_and_hits
                await _persist_provider_call_and_hits(report_id, pass1_trace)
            except Exception as e:  # noqa: BLE001
                log.warning("grok pass1 live-persist failed: %s", e)

        # If user pinned handles or dual-pass disabled, stop after pass 1.
        run_pass2 = (
            opts.enable_dual_pass
            and pass1_trace.success
            and not opts.allowed_x_handles
        )
        candidate_handles = pass1_handles[: opts.max_candidate_handles] if run_pass2 else []

        if not candidate_handles:
            return SearchResult(snippets=pass1_snippets[:max_results], trace=pass1_trace)

        # ---- Pass 2: people → event ------------------------------------
        pass2_trace, pass2_snippets, _hits2, _text2, _h2 = await self._call_x_search(
            model=model,
            time_window=time_window,
            lang=lang,
            opts=opts,
            allowed_handles=candidate_handles,
            user_prompt=self._people_pass_prompt(query, time_window, lang, candidate_handles),
            purpose="search:x_people",
            query=query,
            extra_seed={"pass1_text_excerpt": pass1_text[:1500]},
        )

        combined = pass1_snippets + pass2_snippets
        # Return pass2 trace (gets persisted by multi_search). pass1 was persisted above.
        # Carry total combined cost in pass2 so report.total_cost_usd reflects both.
        # pass2 trace keeps its own cost. multi_search reads `pass1_cost_usd` /
        # `pass1_tokens_total` from extra and adds them to the orchestrator
        # totals so state.total_cost_usd reflects both passes without
        # double-counting in the DB ProviderCall rows (pass1 has its own row).
        pass2_trace.extra = {
            **(pass2_trace.extra or {}),
            "pass": "x_people",
            "candidate_handles": candidate_handles,
            "pass1_cost_usd": pass1_trace.cost_usd,
            "pass1_tokens_total": pass1_trace.tokens_input + pass1_trace.tokens_output,
        }

        return SearchResult(
            snippets=combined[:max_results] if max_results else combined,
            trace=pass2_trace,
        )

    # ------------------------------------------------------------------
    # One Agent Tools call to /v1/responses with tools=[x_search]
    # ------------------------------------------------------------------
    async def _call_x_search(
        self,
        *,
        model: str,
        time_window: TimeRange,
        lang: str,
        opts: GrokOptions,
        allowed_handles: list[str] | None,
        user_prompt: str,
        purpose: str,
        query: str,
        extra_seed: dict | None = None,
    ) -> tuple[ProviderCallTrace, list[RawSnippet], list[dict], str, list[str]]:
        # The Agent Tools API takes BARE tool entries — no per-tool config.
        # All filtering (date range, handle scope) goes into the prompt.
        payload = {
            "model": model,
            "input": [{"role": "user", "content": user_prompt}],
            "tools": [{"type": "x_search"}],
        }

        t0 = time.perf_counter()
        try:
            data = await self._post("/responses", payload)
        except httpx.HTTPStatusError as e:  # noqa: BLE001
            return (
                ProviderCallTrace(
                    provider=self.name, model=model, purpose=purpose, query=query,
                    success=False, error=f"HTTP {e.response.status_code}: {e.response.text[:300]}",
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                    extra=extra_seed or {},
                ),
                [], [], "", [],
            )
        except Exception as e:  # noqa: BLE001
            return (
                ProviderCallTrace(
                    provider=self.name, model=model, purpose=purpose, query=query,
                    success=False, error=str(e)[:400],
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                    extra=extra_seed or {},
                ),
                [], [], "", [],
            )

        latency = int((time.perf_counter() - t0) * 1000)
        snippets, hits, citations_norm, final_text, annotations, handles = (
            _parse_responses_payload(data, lang=lang)
        )

        usage = data.get("usage") or {}
        # Responses API exposes input_tokens / output_tokens; older snapshots
        # may still use prompt_tokens / completion_tokens.
        in_t = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
        out_t = usage.get("output_tokens") or usage.get("completion_tokens") or 0
        reasoning = (usage.get("reasoning_tokens")
                     or (usage.get("output_tokens_details") or {}).get("reasoning_tokens")
                     or 0)
        tool_usage = usage.get("server_side_tool_usage") or {}

        extra: dict[str, Any] = {
            "pass": "x_event" if purpose == "search:x_event" else "x_people",
            "search_results": [
                {**h, "snippet": h.get("snippet"), "kind": h.get("kind", "x_post")}
                for h in hits
            ],
            "citations": citations_norm,
            "annotations": annotations,
            "candidate_handles": handles,
            "final_text": (final_text or "")[:2000],
            "reasoning_tokens": reasoning,
            "tool_usage": tool_usage,
            "x_search": {
                "from_date": time_window.start.date().isoformat(),
                "to_date": time_window.end.date().isoformat(),
                "allowed_x_handles": allowed_handles,
                "excluded_x_handles": opts.excluded_x_handles if not allowed_handles else None,
            },
        }
        if extra_seed:
            extra.update(extra_seed)

        trace = ProviderCallTrace(
            provider=self.name, model=model, purpose=purpose, query=query,
            tokens_input=in_t, tokens_output=out_t,
            cost_usd=_cost(model, in_t, out_t),
            latency_ms=latency, success=True, extra=extra,
        )
        return trace, snippets, hits, final_text or "", handles

    # ------------------------------------------------------------------
    # Prompt builders
    # ------------------------------------------------------------------
    @staticmethod
    def _event_pass_prompt(query: str, tw: TimeRange, lang: str) -> str:
        if lang == "zh":
            return (
                f"使用 x_search 工具，在 X (Twitter) 上检索 {tw.start.date()} 至 {tw.end.date()} "
                f"期间与下述主题相关的高影响力帖子、对话、视频、图片：\n\n主题：{query}\n\n"
                "请尽量做到：\n"
                "1) 同时覆盖中英文圈层；\n"
                "2) 关注观点类发言（KOL / 学者 / 创业者 / 官员 / 资深记者 / 行业分析师），不要纯转载；\n"
                "3) 如果帖子带视频或图片，请阅读视频/图片内容并把关键要点摘出来；\n"
                "4) 在回答末尾用列表给出 8-15 位被识别出的关键发言者的 X handle（@xxx）；\n"
                "5) 关键观点请在文中用 [[N]](url) 形式给出 inline 引用，引用必须可点击。"
            )
        return (
            f"Use the x_search tool to find high-impact X posts (incl. videos / images) about "
            f"the topic below, between {tw.start.date()} and {tw.end.date()}.\n\n"
            f"Topic: {query}\n\n"
            "Goals: (1) cover both English and Chinese spheres; (2) emphasize opinion-bearing "
            "voices (KOLs, scholars, founders, officials, senior journalists, analysts); "
            "(3) if a post contains a video or image, read the media and pull out the core "
            "claims; (4) end your answer with a bulleted list of 8-15 X handles (@xxx) of the "
            "key voices identified; (5) use [[N]](url) inline citations for every claim."
        )

    @staticmethod
    def _people_pass_prompt(query: str, tw: TimeRange, lang: str, handles: list[str]) -> str:
        joined = ", ".join("@" + h.lstrip("@") for h in handles)
        if lang == "zh":
            return (
                f"使用 x_search 工具检索以下 X 账号在 {tw.start.date()} 至 {tw.end.date()} "
                f"期间发表的关于主题的言论：\n\n账号：{joined}\n主题：{query}\n\n"
                "请逐人输出他们的核心观点，并用 [[N]](url) 形式给出 inline 引用。"
                "若帖子包含视频/图片，阅读其内容并标注观点出处为视频或图片。"
            )
        return (
            f"Use x_search to find what these X handles said about the topic between "
            f"{tw.start.date()} and {tw.end.date()}:\n\nHandles: {joined}\nTopic: {query}\n\n"
            "Output each person's core stance with [[N]](url) inline citations. "
            "If a post contains a video or image, read it and note that the statement comes "
            "from video/image."
        )

    # ------------------------------------------------------------------
    # structured_extract / analyze — unchanged, used by non-search nodes
    # ------------------------------------------------------------------
    async def structured_extract(
        self,
        prompt: str,
        schema: type[BaseModel],
        context: str | None = None,
        model: str | None = None,
    ) -> ExtractResult:
        if not self.api_key:
            raise ProviderUnavailable("Grok API key missing")
        model = model or self.default_reasoning_model
        full = f"{prompt}\n\n---\nContext:\n{context}" if context else prompt
        t0 = time.perf_counter()
        data = await self._post("/chat/completions", {
            "model": model,
            "messages": [{"role": "user", "content": full}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"schema": schema.model_json_schema(), "name": schema.__name__},
            },
        })
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        try:
            obj = schema.model_validate_json(text)
        except Exception as e:  # noqa: BLE001
            raise ProviderUnavailable(f"Grok returned invalid schema: {e}") from e
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
            raise ProviderUnavailable("Grok API key missing")
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


# ---------------------------------------------------------------------------
# /v1/responses parser (Agent Tools API shape — same envelope as OpenAI)
# ---------------------------------------------------------------------------
def _parse_responses_payload(
    data: dict, lang: str,
) -> tuple[list[RawSnippet], list[dict], list[dict], str, list[dict], list[str]]:
    """Walk a /v1/responses payload and pull out the parts we care about.

    Returns:
        snippets:    RawSnippet list (one per cited URL / annotation)
        hits:        SearchHit-shaped dicts ready to persist
        citations:   normalised citation dicts ({url, title})
        final_text:  the assistant's final text answer
        annotations: inline citation annotations (url_citation type)
        handles:     candidate X handles extracted from text + URLs
    """
    text_parts: list[str] = []
    annotations: list[dict] = []

    for item in (data.get("output") or []):
        if item.get("type") != "message":
            continue
        for block in item.get("content") or []:
            if block.get("type") in ("output_text", "text"):
                text_parts.append(block.get("text", "") or "")
                for ann in block.get("annotations") or []:
                    if ann.get("type") in ("url_citation", "x_search_result"):
                        annotations.append({
                            "type": ann.get("type"),
                            "url": ann.get("url"),
                            "title": ann.get("title"),
                            "snippet": ann.get("snippet") or ann.get("excerpt"),
                            "start_index": ann.get("start_index"),
                            "end_index": ann.get("end_index"),
                        })
    if not text_parts and isinstance(data.get("output_text"), str):
        text_parts.append(data["output_text"])

    final_text = "".join(text_parts)
    raw_citations = data.get("citations") or []

    hits: list[dict] = []
    citations_norm: list[dict] = []
    seen_urls: set[str] = set()

    for ann in annotations:
        url = ann.get("url")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        si, ei = ann.get("start_index"), ann.get("end_index")
        excerpt = (
            final_text[si:ei]
            if isinstance(si, int) and isinstance(ei, int) and 0 <= si < ei <= len(final_text)
            else ann.get("snippet")
        )
        citations_norm.append({"url": url, "title": ann.get("title"), "cited_text": excerpt})
        hits.append({
            "kind": "x_post",
            "url": url,
            "title": ann.get("title"),
            "snippet": (excerpt or "")[:1000] or None,
            "source_domain": _domain(url),
            "media_type": _media_type_for(url),
        })

    for c in raw_citations:
        if isinstance(c, str):
            url, title, snippet = c, None, None
        elif isinstance(c, dict):
            url = c.get("url") or c.get("uri")
            title = c.get("title")
            snippet = c.get("snippet") or c.get("excerpt") or c.get("cited_text")
        else:
            continue
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        citations_norm.append({"url": url, "title": title, "cited_text": snippet})
        hits.append({
            "kind": "x_post",
            "url": url,
            "title": title,
            "snippet": (snippet or "")[:1000] or None,
            "source_domain": _domain(url),
            "media_type": _media_type_for(url),
        })

    snippets: list[RawSnippet] = [
        RawSnippet(
            title=h.get("title"),
            snippet=(h.get("snippet") or h.get("title") or "")[:1500] or "(x post)",
            url=h.get("url"),
            source_domain=h.get("source_domain"),
            provider="grok",
            lang=lang,
        )
        for h in hits
    ]
    if not snippets and final_text:
        snippets.append(RawSnippet(snippet=final_text[:1500], provider="grok", lang=lang))

    handles = _extract_handles(final_text, hits)
    return snippets, hits, citations_norm, final_text, annotations, handles


def _extract_handles(final_text: str, hits: list[dict]) -> list[str]:
    """Pull X handles out of final_text and citation URLs, dedup-preserve order."""
    seen: dict[str, None] = {}
    # 1) From inline @-mentions in handle list section
    for m in _HANDLE_RE.findall(final_text or ""):
        h = m.lower()
        if h not in seen and 2 <= len(h) <= 15 and h not in _HANDLE_BLACKLIST:
            seen[h] = None
    # 2) From citation URLs (x.com/<handle>/status/...)
    for h in hits:
        url = h.get("url") or ""
        m = _X_URL_RE.search(url)
        if m:
            handle = m.group(1).lower()
            if handle in _PATH_BLACKLIST:
                continue
            if handle not in seen and 2 <= len(handle) <= 15:
                seen[handle] = None
    return list(seen.keys())


_HANDLE_BLACKLIST = {
    "the", "and", "for", "from", "with", "https", "http", "www", "com",
    "twitter", "https", "search", "status", "watch",
}
_PATH_BLACKLIST = {"i", "search", "home", "explore", "settings", "intent", "compose"}
