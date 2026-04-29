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

from sqlalchemy import select

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
    "report_composer": "ReportComposer · 渲染输出",
}


# ---------------------------------------------------------------------------
# Stats helper
# ---------------------------------------------------------------------------
def _compute_node_stats(node_name: str, partial: dict[str, Any]) -> dict[str, Any]:
    """Per-node summary that the UI shows ('collected N, kept M, etc.')."""
    p = partial or {}
    if node_name == "planner":
        plan = p.get("plan")
        return {
            "sub_queries": len(p.get("sub_queries") or []),
            "topic_breakdown": len(getattr(plan, "topic_breakdown", []) or []) if plan else 0,
            "anchor_events_suggested": len(getattr(plan, "suggested_anchor_events", []) or []) if plan else 0,
        }
    if node_name == "multi_search":
        snippets = p.get("raw_snippets") or []
        providers = sorted({s.provider for s in snippets if hasattr(s, "provider")})
        return {"snippets_collected": len(snippets), "providers_used": providers}
    if node_name == "dedup_merger":
        return {"clusters_after_dedup": len(p.get("snippets_clusters") or [])}
    if node_name == "expert_discoverer":
        return {
            "expert_candidates": len(p.get("expert_candidates") or []),
            "events_discovered": len(p.get("discovered_event_names") or []),
        }
    if node_name == "viewpoint_extractor":
        return {"viewpoints_extracted": len(p.get("extracted_viewpoints") or [])}
    if node_name == "cluster_analyzer":
        clusters_by_topic = p.get("clusters_by_topic") or {}
        total = sum(len(v) for v in clusters_by_topic.values())
        return {
            "topics_covered": len(clusters_by_topic),
            "clusters_total": total,
            "section_summaries_written": len(p.get("section_summaries") or {}),
        }
    if node_name == "knowledge_writer":
        return {
            "experts_persisted": len(p.get("persisted_expert_ids") or []),
            "events_persisted": len(p.get("persisted_event_ids") or []),
            "viewpoints_persisted": len(p.get("persisted_viewpoint_ids") or []),
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
        return ReportState(
            report_id=row.id,
            title=row.title,
            focus_topics=list(row.focus_topics or []),
            time_range_start=start,
            time_range_end=end,
            providers_enabled=list(row.providers_enabled or []),
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
