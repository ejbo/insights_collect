"""Agent runs / provider calls observability."""

import asyncio
import json

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.agents.runner import NODE_LABELS, NODE_ORDER
from app.db import models
from app.db.session import SessionLocal, get_session

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.get("/graph-meta")
async def graph_meta():
    """Static metadata about the LangGraph node order — used by the UI stepper."""
    return {
        "nodes": [{"name": n, "label": NODE_LABELS.get(n, n)} for n in NODE_ORDER],
    }


@router.get("/report/{report_id}/agent-runs")
async def list_agent_runs(report_id: int, session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(
        select(models.AgentRun)
        .where(models.AgentRun.report_id == report_id)
        .order_by(models.AgentRun.id)
    )).scalars().all()
    return rows


@router.get("/report/{report_id}/provider-calls")
async def list_provider_calls(report_id: int, session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(
        select(models.ProviderCall)
        .where(models.ProviderCall.report_id == report_id)
        .order_by(models.ProviderCall.id)
    )).scalars().all()
    return rows


@router.get("/report/{report_id}/stream")
async def stream_status(report_id: int):
    """Long-poll-style SSE: emit status snapshots while report is running."""
    async def event_iter():
        last_status = None
        last_call_id = 0
        while True:
            async with SessionLocal() as session:
                report = (await session.execute(
                    select(models.Report).where(models.Report.id == report_id)
                )).scalar_one_or_none()
                if not report:
                    yield {"event": "error", "data": "report not found"}
                    return

                calls = (await session.execute(
                    select(models.ProviderCall)
                    .where(
                        models.ProviderCall.report_id == report_id,
                        models.ProviderCall.id > last_call_id,
                    )
                    .order_by(models.ProviderCall.id)
                )).scalars().all()
                for c in calls:
                    last_call_id = max(last_call_id, c.id or 0)
                    yield {
                        "event": "provider_call",
                        "data": json.dumps({
                            "provider": c.provider,
                            "model": c.model,
                            "purpose": c.purpose,
                            "tokens": (c.tokens_input or 0) + (c.tokens_output or 0),
                            "cost_usd": c.cost_usd,
                            "latency_ms": c.latency_ms,
                            "success": c.success,
                            "error": c.error,
                        }),
                    }

                if report.status != last_status:
                    last_status = report.status
                    yield {
                        "event": "status",
                        "data": json.dumps({
                            "status": report.status.value,
                            "total_cost_usd": report.total_cost_usd,
                            "total_tokens": report.total_tokens,
                            "error": report.error,
                        }),
                    }

                if report.status in (
                    models.ReportStatus.succeeded,
                    models.ReportStatus.failed,
                    models.ReportStatus.cancelled,
                ):
                    yield {"event": "done", "data": report.status.value}
                    return
            await asyncio.sleep(2)

    return EventSourceResponse(event_iter())
