"""Driver that runs the report graph and persists per-node progress.

Streams the LangGraph in `["updates", "values"]` modes so we get:
  - per-node finish event (to write `agent_runs` row + counts)
  - cumulative state snapshot (to compute final state without re-invoking)
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from app.agents.graph import report_graph
from app.agents.state import ReportState
from app.db import models
from app.db.session import SessionLocal

log = logging.getLogger(__name__)


# Stable node order for frontend stepper rendering.
NODE_ORDER = [
    "planner",
    "multi_search",
    "dedup_merger",
    "expert_discoverer",
    "viewpoint_extractor",
    "cluster_analyzer",
    "knowledge_writer",
    "event_curator",
    "report_composer",
]

NODE_LABELS = {
    "planner": "Planner · 拆解主题",
    "multi_search": "MultiSearch · 多源并行检索",
    "dedup_merger": "DedupMerger · 跨源去重",
    "expert_discoverer": "ExpertDiscoverer · 双向挖人",
    "viewpoint_extractor": "ViewpointExtractor · 7 元组抽取",
    "cluster_analyzer": "ClusterAnalyzer · 共识/分歧/重点/启示",
    "knowledge_writer": "KnowledgeWriter · 落库",
    "event_curator": "EventCurator · 事件清洗 / 跨报告合并",
    "report_composer": "ReportComposer · 渲染输出",
}


# ---------------------------------------------------------------------------
# Stats helper
# ---------------------------------------------------------------------------
def _compute_node_stats(node_name: str, partial: dict[str, Any]) -> dict[str, Any]:
    """Per-node summary the UI renders. Includes a small `details` payload
    so each stage row can show *what* was produced, not just counts.

    Bounded: lists capped to ~30 items, strings to ~200 chars. The whole
    blob is JSON-serialised into agent_runs.state_out.
    """
    p = partial or {}

    if node_name == "planner":
        plan = p.get("plan")
        sqs = p.get("sub_queries") or []
        return {
            "sub_queries_count": len(sqs),
            "topic_breakdown_count": len(getattr(plan, "topic_breakdown", []) or []) if plan else 0,
            "anchor_events_count": len(getattr(plan, "suggested_anchor_events", []) or []) if plan else 0,
            "sub_queries": [
                {"text": (s.text or "")[:160], "lang": s.lang, "angle": s.angle}
                for s in sqs[:30]
            ],
            "anchor_events": list(getattr(plan, "suggested_anchor_events", []) or [])[:20] if plan else [],
        }

    if node_name == "multi_search":
        snippets = p.get("raw_snippets") or []
        traces = p.get("provider_traces") or []
        providers = sorted({s.provider for s in snippets if hasattr(s, "provider")})
        per_provider: dict[str, dict[str, Any]] = {}
        for t in traces:
            row = per_provider.setdefault(t.provider, {
                "calls": 0, "errors": 0, "snippets": 0,
                "tokens": 0, "cost_usd": 0.0, "latency_total_ms": 0,
            })
            row["calls"] += 1
            if not t.success:
                row["errors"] += 1
            row["tokens"] += (t.tokens_input or 0) + (t.tokens_output or 0)
            row["cost_usd"] = round(row["cost_usd"] + (t.cost_usd or 0.0), 6)
            row["latency_total_ms"] += t.latency_ms or 0
        for s in snippets:
            row = per_provider.get(getattr(s, "provider", None))
            if row is not None:
                row["snippets"] += 1
        return {
            "snippets_collected": len(snippets),
            "providers_used": providers,
            "calls_total": len(traces),
            "calls_failed": sum(1 for t in traces if not t.success),
            "per_provider": per_provider,
        }

    if node_name == "dedup_merger":
        clusters = p.get("snippets_clusters") or []
        domain_count: dict[str, int] = {}
        for c in clusters:
            d = c.get("domain")
            if d:
                domain_count[d] = domain_count.get(d, 0) + 1
        top_domains = sorted(domain_count.items(), key=lambda x: -x[1])[:10]
        return {
            "clusters_after_dedup": len(clusters),
            "top_domains": [{"domain": d, "count": n} for d, n in top_domains],
        }

    if node_name == "expert_discoverer":
        cands = p.get("expert_candidates") or []
        events = p.get("discovered_event_names") or []
        return {
            "expert_candidates_count": len(cands),
            "events_discovered_count": len(events),
            "candidates": [
                {
                    "name": getattr(c, "name", None),
                    "role": getattr(c, "role", None),
                    "affiliations": list(getattr(c, "affiliations", []) or [])[:3],
                    "relevance": getattr(c, "relevance_score", None),
                    "rationale": (getattr(c, "rationale", "") or "")[:200],
                }
                for c in cands[:30]
            ],
            "events": list(events)[:20],
        }

    if node_name == "viewpoint_extractor":
        vps = p.get("extracted_viewpoints") or []
        return {
            "viewpoints_extracted": len(vps),
            "viewpoints": [
                {
                    "expert_name": getattr(v, "expert_name", None),
                    "expert_role": getattr(v, "expert_role", None),
                    "claim_when": v.claim_when.date().isoformat() if getattr(v, "claim_when", None) else None,
                    "claim_where": getattr(v, "claim_where", None),
                    "claim_what": (getattr(v, "claim_what", "") or "")[:200],
                    "claim_medium": getattr(v, "claim_medium", None),
                    "claim_source_url": getattr(v, "claim_source_url", None),
                    "confidence": getattr(v, "confidence", None),
                }
                for v in vps[:40]
            ],
        }

    if node_name == "cluster_analyzer":
        cbt = p.get("clusters_by_topic") or {}
        total = sum(len(v) for v in cbt.values())
        return {
            "topics_covered": len(cbt),
            "clusters_total": total,
            "section_summaries_written": len(p.get("section_summaries") or {}),
            "clusters_by_topic": {
                topic: [
                    {"label": getattr(c, "label", ""), "kind": getattr(c, "kind", "")}
                    for c in clusters[:8]
                ]
                for topic, clusters in cbt.items()
            },
            "section_summaries": {
                t: (s or "")[:240]
                for t, s in (p.get("section_summaries") or {}).items()
            },
        }

    if node_name == "knowledge_writer":
        return {
            "experts_persisted": len(p.get("persisted_expert_ids") or []),
            "events_persisted": len(p.get("persisted_event_ids") or []),
            "viewpoints_persisted": len(p.get("persisted_viewpoint_ids") or []),
            "viewpoint_ids": list(p.get("persisted_viewpoint_ids") or []),
            "expert_ids": list(p.get("persisted_expert_ids") or []),
        }

    if node_name == "report_composer":
        return {
            "md_generated": bool(p.get("md_path")),
            "outline_generated": bool(p.get("outline_json_path")),
            "pdf_generated": bool(p.get("pdf_path")),
        }

    return {}


def _provider_traces_summary(partial: dict[str, Any]) -> tuple[int, float]:
    traces = partial.get("provider_traces") or []
    tokens = sum((t.tokens_input or 0) + (t.tokens_output or 0) for t in traces)
    cost = sum(t.cost_usd or 0.0 for t in traces)
    # Multi-pass providers (grok dual x_search) carry earlier-pass totals on
    # `extra` because those were persisted as separate ProviderCall rows. Roll
    # them in so the AgentRun row matches the report total.
    for t in traces:
        ex = getattr(t, "extra", None) or {}
        cost += ex.get("pass1_cost_usd") or 0.0
        tokens += ex.get("pass1_tokens_total") or 0
    return tokens, cost


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
async def _load_initial_state(report_id: int) -> ReportState | None:
    async with SessionLocal() as session:
        row = (await session.execute(
            select(models.Report).where(models.Report.id == report_id)
        )).scalar_one_or_none()
        if row is None:
            return None
        end = row.time_range_end or datetime.utcnow()
        start = row.time_range_start or end
        all_options = dict(row.providers_options or {})
        # main_model stashed under "__main__" to avoid a new column
        main_model = all_options.pop("__main__", None) or {
            "provider": "openai", "model": "gpt-5.5",
        }
        return ReportState(
            report_id=row.id,
            title=row.title,
            focus_topics=list(row.focus_topics or []),
            time_range_start=start,
            time_range_end=end,
            providers_enabled=list(row.providers_enabled or []),
            providers_options=all_options,
            main_model=main_model,
            md_template_id=row.md_template_id,
            outline_template_id=row.outline_template_id,
            cost_cap_usd=row.cost_cap_usd,
            max_reflection_rounds=row.max_reflection_rounds,
            raw_snippets=[],
            provider_traces=[],
            total_cost_usd=0.0,
            total_tokens=0,
            errors=[],
            notes=[],
            extras={},
        )


async def _write_agent_run(
    report_id: int,
    node_name: str,
    partial: dict[str, Any],
    started_at: datetime,
    finished_at: datetime,
) -> None:
    """Persist this node's AgentRun row, then refresh the parent report's
    running cost/token totals so the UI header sees them update live (instead
    of staying $0 until the very end)."""
    stats = _compute_node_stats(node_name, partial)
    tokens, cost = _provider_traces_summary(partial)
    errors = partial.get("errors") or []
    err_str = "; ".join(errors)[:1000] if errors else None
    async with SessionLocal() as session:
        session.add(models.AgentRun(
            report_id=report_id,
            graph_node=node_name,
            state_in=None,
            state_out=stats,
            tokens=tokens,
            cost_usd=cost,
            started_at=started_at,
            finished_at=finished_at,
            error=err_str,
        ))
        await session.flush()

        # Sum across all agent_runs for this report (including the one we just
        # added) and push the running totals onto the report row.
        running_cost = (await session.execute(
            select(func.coalesce(func.sum(models.AgentRun.cost_usd), 0.0))
            .where(models.AgentRun.report_id == report_id)
        )).scalar() or 0.0
        running_tokens = (await session.execute(
            select(func.coalesce(func.sum(models.AgentRun.tokens), 0))
            .where(models.AgentRun.report_id == report_id)
        )).scalar() or 0

        report_row = (await session.execute(
            select(models.Report).where(models.Report.id == report_id)
        )).scalar_one_or_none()
        if report_row is not None:
            report_row.total_cost_usd = float(running_cost)
            report_row.total_tokens = int(running_tokens)

        await session.commit()


async def _persist_provider_calls(report_id: int, traces: list) -> None:
    if not traces:
        return
    async with SessionLocal() as session:
        for t in traces:
            session.add(models.ProviderCall(
                report_id=report_id,
                provider=t.provider,
                model=t.model,
                purpose=t.purpose,
                query=t.query,
                tokens_input=t.tokens_input,
                tokens_output=t.tokens_output,
                cost_usd=t.cost_usd,
                latency_ms=t.latency_ms,
                success=t.success,
                error=t.error,
            ))
        await session.commit()


async def _mark_report(report_id: int, **fields) -> None:
    async with SessionLocal() as session:
        row = (await session.execute(
            select(models.Report).where(models.Report.id == report_id)
        )).scalar_one_or_none()
        if not row:
            return
        for k, v in fields.items():
            setattr(row, k, v)
        await session.commit()


async def run_report(report_id: int) -> None:
    state_in = await _load_initial_state(report_id)
    if not state_in:
        log.error("run_report: report %s not found", report_id)
        return

    await _mark_report(
        report_id,
        status=models.ReportStatus.running,
        started_at=datetime.utcnow(),
        error=None,
    )

    final_state: dict = dict(state_in)
    last_node_finish = datetime.utcnow()
    accumulated_traces: list = []

    try:
        config = {"configurable": {"thread_id": f"report-{report_id}"}}
        async for mode, chunk in report_graph.astream(
            state_in, config=config, stream_mode=["updates", "values"]
        ):
            if mode == "updates":
                for node_name, partial in chunk.items():
                    now = datetime.utcnow()
                    await _write_agent_run(
                        report_id=report_id,
                        node_name=node_name,
                        partial=partial,
                        started_at=last_node_finish,
                        finished_at=now,
                    )
                    # collect provider traces for ProviderCall persistence
                    accumulated_traces.extend(partial.get("provider_traces") or [])
                    last_node_finish = now
            elif mode == "values":
                final_state = chunk
    except asyncio.CancelledError:
        log.warning("run_report %s cancelled (process shutdown / hot reload)", report_id)
        await _persist_provider_calls(report_id, accumulated_traces)
        await _mark_report(
            report_id,
            status=models.ReportStatus.cancelled,
            finished_at=datetime.utcnow(),
            error="cancelled (process shutdown)",
        )
        raise
    except Exception as e:  # noqa: BLE001
        log.exception("graph crashed")
        await _persist_provider_calls(report_id, accumulated_traces)
        await _mark_report(
            report_id,
            status=models.ReportStatus.failed,
            finished_at=datetime.utcnow(),
            error=f"{e}\n{traceback.format_exc()[:2000]}",
        )
        return

    await _persist_provider_calls(report_id, accumulated_traces)

    errors = final_state.get("errors") or []
    final_status = (
        models.ReportStatus.failed
        if not final_state.get("md_path")
        else models.ReportStatus.succeeded
    )
    await _mark_report(
        report_id,
        status=final_status,
        finished_at=datetime.utcnow(),
        total_cost_usd=final_state.get("total_cost_usd", 0.0),
        total_tokens=final_state.get("total_tokens", 0),
        error="; ".join(errors[:5]) if errors and final_status == models.ReportStatus.failed else None,
    )
