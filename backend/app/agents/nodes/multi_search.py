"""MultiSearch — fan out sub-queries × providers, stream snippets as they arrive.

Behavior:
  - asyncio.as_completed: as soon as one task finishes, write its ProviderCall row
    to DB so the UI stepper / right-pane sees live progress.
  - Each provider.search() is wrapped in asyncio.wait_for(..., PROVIDER_CALL_TIMEOUT_S)
    to prevent any single hung HTTP from blocking the whole node.
  - Returns the cumulative snippet/trace lists at the end (same shape as before).
"""

from __future__ import annotations

import asyncio
import logging
import time

from app.agents.state import ReportState
from app.config import get_settings
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


_LANG_PROVIDER_BIAS = {
    "zh": ["qwen", "deepseek", "perplexity", "anthropic", "openai", "gemini", "grok"],
    "en": ["perplexity", "openai", "anthropic", "gemini", "grok"],
    "mixed": ["anthropic", "openai", "gemini", "perplexity", "qwen", "grok"],
}


async def _persist_provider_call(report_id: int | None, trace: ProviderCallTrace) -> None:
    """Insert a single ProviderCall row immediately (no batching)."""
    if report_id is None:
        return
    try:
        async with SessionLocal() as session:
            session.add(models.ProviderCall(
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
            ))
            await session.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("failed to persist provider_call live: %s", e)


async def _do_search_with_timeout(
    prov: SearchProvider,
    query: str,
    tw: TimeRange,
    lang: str,
    max_results: int,
    timeout_s: int,
) -> SearchResult:
    """Run prov.search with a timeout; if it expires, return an empty SearchResult
    carrying a failed trace (success=False, error="timeout (Ns)")."""
    t0 = time.perf_counter()
    try:
        return await asyncio.wait_for(
            prov.search(query, tw, lang=lang, max_results=max_results),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        latency = int((time.perf_counter() - t0) * 1000)
        log.warning("provider %s timeout after %ss (query=%.80s)", prov.name, timeout_s, query)
        return SearchResult(
            snippets=[],
            trace=ProviderCallTrace(
                provider=prov.name,
                model=getattr(prov, "default_search_model", ""),
                purpose="search",
                query=query,
                success=False,
                error=f"timeout ({timeout_s}s)",
                latency_ms=latency,
            ),
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

    settings = get_settings()
    timeout_s = settings.provider_call_timeout_s
    report_id = state.get("report_id")
    tw = TimeRange(start=state["time_range_start"], end=state["time_range_end"])

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
        "multi_search: dispatching %d tasks across %d providers (timeout=%ss)",
        len(plan), len(providers), timeout_s,
    )

    tasks = [
        asyncio.create_task(_do_search_with_timeout(prov, q, tw, lang, 8, timeout_s))
        for prov, q, lang in plan
    ]

    snippets: list = []
    traces: list = []
    cost = 0.0
    tokens = 0
    errors: list[str] = []
    completed = 0

    for fut in asyncio.as_completed(tasks):
        result: SearchResult = await fut
        completed += 1

        # Live persist to provider_calls so frontend sees it within ~3s
        await _persist_provider_call(report_id, result.trace)

        snippets.extend(result.snippets)
        traces.append(result.trace)
        cost += result.trace.cost_usd or 0.0
        tokens += (result.trace.tokens_input or 0) + (result.trace.tokens_output or 0)
        if not result.trace.success and result.trace.error:
            errors.append(f"{result.trace.provider}: {result.trace.error}")

        if completed % 5 == 0 or completed == len(tasks):
            log.info("multi_search progress: %d/%d done, %d snippets so far",
                     completed, len(tasks), len(snippets))

    return {
        "raw_snippets": snippets,
        "provider_traces": traces,
        "total_cost_usd": cost,
        "total_tokens": tokens,
        "errors": errors,
        "notes": [
            f"multi_search: {len(snippets)} snippets / {len(tasks)} calls "
            f"({sum(1 for t in traces if not t.success)} failed)"
        ],
    }
