"""MultiSearch — fan out sub-queries × providers, stream snippets as they arrive.

Behavior:
  - Each provider task runs to completion. The loop exits naturally when every
    task has either returned a result or raised. Persists each ProviderCall
    row the moment it lands so the UI shows live progress.
  - No timeouts of any kind — slow providers (Anthropic adaptive thinking,
    Gemini deep grounding) get to finish on their own. The user has a
    「立即下一步」button that flips an in-process Event when a provider hangs;
    we detach the still-pending tasks at that point and move on.
"""

from __future__ import annotations

import asyncio
import logging
import time

from app.agents.control import clear as clear_advance, get_advance_event
from app.agents.state import ReportState
from app.db import models
from app.db.session import SessionLocal
from app.providers.base import (
    ProviderCallTrace,
    SearchProvider,
    SearchResult,
    TimeRange,
)
from app.providers.registry import build_providers

log = logging.getLogger(__name__)


# Strong refs to tasks we've cancelled but don't want to await — they'll
# finish on their own once their underlying IO unwinds. Without this set
# they might be GC'd mid-flight.
_DETACHED: set[asyncio.Task] = set()


_LANG_PROVIDER_BIAS = {
    "zh": ["qwen", "deepseek", "perplexity", "anthropic", "openai", "gemini", "grok"],
    "en": ["perplexity", "openai", "anthropic", "gemini", "grok"],
    "mixed": ["anthropic", "openai", "gemini", "perplexity", "qwen", "grok"],
}


async def _persist_provider_call_and_hits(
    report_id: int | None, trace: ProviderCallTrace,
) -> None:
    """Insert a ProviderCall row + per-search-result SearchHit rows in one tx."""
    if report_id is None:
        return
    try:
        async with SessionLocal() as session:
            # ProviderCall first so we have an ID for the FK
            extra_for_call = {
                k: v for k, v in (trace.extra or {}).items()
                if k in ("effort", "max_uses", "max_fetches", "task_budget",
                         "stop_reason", "thinking_summary", "final_text",
                         "cache_read_tokens", "cache_creation_tokens", "model",
                         "search_results_total",
                         # x_search-specific fields
                         "pass", "candidate_handles", "tool_usage",
                         "reasoning_tokens", "cached_prompt_tokens", "x_search",
                         "pass1_cost_usd", "pass1_tokens_total",
                         "pass1_text_excerpt")
            }
            pc = models.ProviderCall(
                report_id=report_id,
                provider=trace.provider,
                model=trace.model,
                purpose=trace.purpose,
                query=trace.query,
                tokens_input=trace.tokens_input,
                tokens_output=trace.tokens_output,
                cost_usd=trace.cost_usd,
                latency_ms=trace.latency_ms,
                success=trace.success,
                error=trace.error,
                extra=extra_for_call or None,
            )
            session.add(pc)
            await session.flush()
            # SearchHits (web_search results + web_fetch outputs + x_post hits)
            for sr in (trace.extra or {}).get("search_results") or []:
                if not isinstance(sr, dict):
                    continue
                hit_extra = {}
                if sr.get("media_type") and sr["media_type"] != "text":
                    hit_extra["media_type"] = sr["media_type"]
                session.add(models.SearchHit(
                    report_id=report_id,
                    provider_call_id=pc.id,
                    provider=trace.provider,
                    kind=sr.get("kind") or "web_search",
                    query=sr.get("query") or trace.query,
                    url=sr.get("url"),
                    title=sr.get("title"),
                    snippet=sr.get("snippet"),
                    source_domain=sr.get("source_domain"),
                    page_age=sr.get("page_age"),
                    extra=hit_extra or None,
                ))
            # Citations (only for the call that produced them) — store on extra
            citations = (trace.extra or {}).get("citations") or []
            if citations:
                pc.extra = {**(pc.extra or {}), "citations_count": len(citations)}
                # Store citations as a SearchHit with kind=citation if URL is novel
                seen_urls = {sr.get("url") for sr in (trace.extra or {}).get("search_results") or []}
                for c in citations:
                    if not isinstance(c, dict): continue
                    url = c.get("url")
                    if not url or url in seen_urls: continue
                    session.add(models.SearchHit(
                        report_id=report_id,
                        provider_call_id=pc.id,
                        provider=trace.provider,
                        kind="citation",
                        query=trace.query,
                        url=url,
                        title=c.get("title"),
                        snippet=(c.get("cited_text") or "")[:1000],
                        citations=[c],
                    ))
            await session.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("failed to persist provider_call/search_hits live: %s", e)


# Back-compat alias for any external caller
_persist_provider_call = _persist_provider_call_and_hits


async def _do_search(
    prov: SearchProvider,
    query: str,
    tw: TimeRange,
    lang: str,
    max_results: int,
    options: dict | None = None,
    report_id: int | None = None,
) -> SearchResult:
    """Run prov.search and translate any exception into a failed trace, but
    don't impose a deadline — the user wants slow providers to finish."""
    t0 = time.perf_counter()
    try:
        return await prov.search(
            query, tw, lang=lang, max_results=max_results, options=options,
            report_id=report_id,
        )
    except Exception as e:  # noqa: BLE001
        latency = int((time.perf_counter() - t0) * 1000)
        log.exception("provider %s raised", prov.name)
        return SearchResult(
            snippets=[],
            trace=ProviderCallTrace(
                provider=prov.name,
                model=getattr(prov, "default_search_model", ""),
                purpose="search",
                query=query,
                success=False,
                error=str(e)[:300],
                latency_ms=latency,
            ),
        )


async def multi_search_node(state: ReportState) -> dict:
    sub_queries = state.get("sub_queries") or []
    if not sub_queries:
        return {"errors": ["multi_search: no sub_queries"]}

    enabled = set(state.get("providers_enabled") or [])
    async with SessionLocal() as session:
        providers = await build_providers(session)
    if enabled:
        providers = {k: v for k, v in providers.items() if k in enabled}
    if not providers:
        return {"errors": ["multi_search: no provider available — configure API keys in /settings"]}

    report_id = state.get("report_id")
    tw = TimeRange(start=state["time_range_start"], end=state["time_range_end"])
    providers_options = state.get("providers_options") or {}

    # Build (provider, query, lang) plan
    plan: list[tuple[SearchProvider, str, str]] = []
    for sq in sub_queries:
        if sq.target_providers:
            chosen = [providers[p] for p in sq.target_providers if p in providers]
        else:
            order = _LANG_PROVIDER_BIAS.get(sq.lang, list(providers.keys()))
            chosen = [providers[p] for p in order if p in providers]
            chosen = chosen[: max(3, len(providers))]
        for prov in chosen:
            plan.append((prov, sq.text, sq.lang))

    log.info(
        "multi_search: dispatching %d tasks across %d providers (no per-call timeout)",
        len(plan), len(providers),
    )

    # max_results=0 → no artificial cap. Each provider returns whatever the
    # user-configured tool budget produces (anthropic = max_uses × ~5–10,
    # gemini = grounding_chunks count, openai = annotation count).
    tasks = [
        asyncio.create_task(_do_search(
            prov, q, tw, lang, 0,
            options=providers_options.get(prov.name) or None,
            report_id=report_id,
        ))
        for prov, q, lang in plan
    ]

    snippets: list = []
    traces: list = []
    cost = 0.0
    tokens = 0
    errors: list[str] = []
    completed = 0
    advanced = False
    cancelled_count = 0

    # Wait either for any task to finish OR for the user to press 「立即下一步」.
    # The advance event is in-process; the API endpoint flips it. No timers
    # of any kind — providers run to completion unless the user intervenes.
    advance_event = get_advance_event(report_id) if report_id else asyncio.Event()
    advance_waiter: asyncio.Task | None = (
        asyncio.create_task(advance_event.wait()) if report_id else None
    )

    pending: set[asyncio.Task] = set(tasks)
    try:
        while pending:
            if advance_event.is_set():
                advanced = True
                break

            wait_set: set = set(pending)
            if advance_waiter is not None:
                wait_set.add(advance_waiter)
            done, _ = await asyncio.wait(
                wait_set,
                return_when=asyncio.FIRST_COMPLETED,
            )
            stop = False
            for fut in done:
                if fut is advance_waiter:
                    advanced = True
                    stop = True
                    continue
                pending.discard(fut)  # type: ignore[arg-type]
                try:
                    result: SearchResult = await fut
                except asyncio.CancelledError:
                    continue
                completed += 1
                await _persist_provider_call_and_hits(report_id, result.trace)
                snippets.extend(result.snippets)
                traces.append(result.trace)
                cost += result.trace.cost_usd or 0.0
                tokens += (result.trace.tokens_input or 0) + (result.trace.tokens_output or 0)
                # Providers that ran multi-pass (e.g. grok x_search dual pass)
                # already persisted earlier passes as their own ProviderCall
                # rows. Add their cost/tokens here so state.total_cost_usd
                # reflects the full work without double-counting in DB.
                trace_extra = result.trace.extra or {}
                cost += trace_extra.get("pass1_cost_usd") or 0.0
                tokens += trace_extra.get("pass1_tokens_total") or 0
                if not result.trace.success and result.trace.error:
                    errors.append(f"{result.trace.provider}: {result.trace.error}")
                if completed % 5 == 0 or (not pending and not advanced):
                    log.info(
                        "multi_search progress: %d/%d done, %d snippets so far",
                        completed, len(tasks), len(snippets),
                    )
            if stop:
                break

        if advanced and pending:
            cancelled_count = len(pending)
            log.info(
                "multi_search: user advanced — detaching %d pending task(s)",
                cancelled_count,
            )
            # Fire-and-forget: cancel each and move on RIGHT NOW. We don't
            # `await asyncio.gather(*pending)` because anthropic streams
            # under no-read-timeout may take many seconds (or never) to
            # observe the cancellation, and the user's whole point in
            # pressing "跳过" is to *not* wait for that. The task refs are
            # parked in `_DETACHED` so the GC doesn't reap them; each one
            # self-removes via done_callback when it eventually unwinds.
            for p in pending:
                p.cancel()
                _DETACHED.add(p)
                p.add_done_callback(_DETACHED.discard)
            pending.clear()
    finally:
        if advance_waiter is not None and not advance_waiter.done():
            advance_waiter.cancel()
            try:
                await advance_waiter
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if report_id:
            clear_advance(report_id)

    note = (
        f"multi_search: {len(snippets)} snippets / {completed} calls "
        f"({sum(1 for t in traces if not t.success)} failed)"
    )
    if advanced:
        note += f" · 已按用户请求提前进入下一步（取消 {cancelled_count} 个未完成的调用）"

    return {
        "raw_snippets": snippets,
        "provider_traces": traces,
        "total_cost_usd": cost,
        "total_tokens": tokens,
        "errors": errors,
        "notes": [note],
    }
