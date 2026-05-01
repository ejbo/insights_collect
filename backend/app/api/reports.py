"""Reports endpoints."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.control import request_advance
from app.agents.runner import run_report
from app.db import models
from app.db.session import get_session
from app.schemas.api import CreateReportRequest

router = APIRouter(prefix="/api/reports", tags=["reports"])

# Strong refs to in-flight tasks keyed by report_id, so we can cancel a
# specific run on demand. The done-callback removes the entry when the task
# finishes (either successfully or via cancellation).
_RUNNING: dict[int, asyncio.Task] = {}


def _spawn(report_id: int, coro) -> asyncio.Task:
    t = asyncio.create_task(coro)
    _RUNNING[report_id] = t
    t.add_done_callback(lambda _t: _RUNNING.pop(report_id, None))
    return t


def _naive_utc(dt: datetime) -> datetime:
    """DB columns are TIMESTAMP WITHOUT TIME ZONE; coerce aware → naive UTC."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


@router.post("")
async def create_report(
    payload: CreateReportRequest,
    session: AsyncSession = Depends(get_session),
):
    if payload.time_range_end < payload.time_range_start:
        raise HTTPException(400, "time_range_end must be on or after time_range_start")

    # Stash main_model under providers_options.__main__ so we don't need a new column
    provs_opts = dict(payload.providers_options or {})
    if payload.main_model is not None:
        provs_opts["__main__"] = payload.main_model.model_dump(exclude_none=False)

    row = models.Report(
        title=payload.title,
        focus_topics=payload.focus_topics,
        time_range_start=_naive_utc(payload.time_range_start),
        time_range_end=_naive_utc(payload.time_range_end),
        md_template_id=payload.md_template_id,
        outline_template_id=payload.outline_template_id,
        providers_enabled=payload.providers_enabled,
        providers_options=provs_opts or None,
        max_reflection_rounds=payload.max_reflection_rounds,
        cost_cap_usd=payload.cost_cap_usd,
        status=models.ReportStatus.pending,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)

    _spawn(row.id, run_report(row.id))
    return row


@router.get("")
async def list_reports(
    limit: int = 30,
    session: AsyncSession = Depends(get_session),
):
    rows = (
        await session.execute(
            select(models.Report).order_by(desc(models.Report.created_at)).limit(limit)
        )
    ).scalars().all()
    return rows


@router.get("/{report_id}")
async def get_report(report_id: int, session: AsyncSession = Depends(get_session)):
    row = (await session.execute(
        select(models.Report).where(models.Report.id == report_id)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "report not found")
    return row


@router.delete("/{report_id}")
async def delete_report(
    report_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Hard delete a report and all of its derived rows. Cancels the running
    task first if any, then sweeps child tables (no FK CASCADE in the schema)."""
    # Cancel an in-flight task so it can't keep writing rows after we delete.
    t = _RUNNING.get(report_id)
    if t is not None and not t.done():
        t.cancel()

    row = (await session.execute(
        select(models.Report).where(models.Report.id == report_id)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "report not found")

    # Best-effort delete generated artefacts on disk.
    for path_attr in ("md_path", "outline_json_path", "pdf_path"):
        p = getattr(row, path_attr, None)
        if p:
            try:
                Path(p).unlink(missing_ok=True)
            except OSError:
                pass

    await session.execute(delete(models.SearchHit).where(models.SearchHit.report_id == report_id))
    await session.execute(delete(models.ProviderCall).where(models.ProviderCall.report_id == report_id))
    await session.execute(delete(models.AgentRun).where(models.AgentRun.report_id == report_id))
    await session.execute(delete(models.ReportSection).where(models.ReportSection.report_id == report_id))
    await session.execute(delete(models.Report).where(models.Report.id == report_id))
    await session.commit()
    return {"ok": True, "deleted_id": report_id}


@router.get("/{report_id}/markdown", response_class=PlainTextResponse)
async def get_report_markdown(report_id: int, session: AsyncSession = Depends(get_session)):
    row = (await session.execute(
        select(models.Report).where(models.Report.id == report_id)
    )).scalar_one_or_none()
    if not row or not row.md_path:
        raise HTTPException(404, "markdown not yet rendered")
    p = Path(row.md_path)
    if not p.exists():
        raise HTTPException(404, "markdown file missing on disk")
    return p.read_text(encoding="utf-8")


@router.get("/{report_id}/outline")
async def get_report_outline(report_id: int, session: AsyncSession = Depends(get_session)):
    row = (await session.execute(
        select(models.Report).where(models.Report.id == report_id)
    )).scalar_one_or_none()
    if not row or not row.outline_json_path:
        raise HTTPException(404, "outline not yet rendered")
    p = Path(row.outline_json_path)
    if not p.exists():
        raise HTTPException(404, "outline file missing on disk")
    import json
    return json.loads(p.read_text(encoding="utf-8"))


@router.get("/{report_id}/pdf")
async def get_report_pdf(report_id: int, session: AsyncSession = Depends(get_session)):
    row = (await session.execute(
        select(models.Report).where(models.Report.id == report_id)
    )).scalar_one_or_none()
    if not row or not row.pdf_path:
        raise HTTPException(404, "pdf not yet rendered")
    p = Path(row.pdf_path)
    if not p.exists():
        raise HTTPException(404, "pdf file missing on disk")
    return FileResponse(p, media_type="application/pdf", filename=p.name)


@router.get("/{report_id}/sections")
async def get_report_sections(report_id: int, session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(
        select(models.ReportSection)
        .where(models.ReportSection.report_id == report_id)
        .order_by(models.ReportSection.order)
    )).scalars().all()
    return rows


@router.post("/{report_id}/advance")
async def advance_report(report_id: int):
    """User clicked 「立即进入下一步」 — flips the in-process advance flag so
    the running multi_search node cancels its remaining sub-tasks and returns
    with whatever it already has. No-op if the report isn't currently running.
    """
    request_advance(report_id)
    return {"ok": True, "advanced_at": datetime.utcnow().isoformat()}


@router.post("/{report_id}/cancel")
async def cancel_report(
    report_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Hard-cancel: aborts the asyncio task running this report's graph.
    The runner's CancelledError handler marks status=cancelled and persists
    whatever traces it had accumulated. If the task isn't in our process
    (e.g. server restarted), we just flip the DB row to cancelled."""
    t = _RUNNING.get(report_id)
    cancelled_in_process = False
    if t is not None and not t.done():
        t.cancel()
        cancelled_in_process = True

    if not cancelled_in_process:
        # Best-effort DB update for orphaned runs (server restart etc.)
        row = (await session.execute(
            select(models.Report).where(models.Report.id == report_id)
        )).scalar_one_or_none()
        if row and row.status == models.ReportStatus.running:
            row.status = models.ReportStatus.cancelled
            row.finished_at = datetime.utcnow()
            row.error = "cancelled by user (no in-process task)"
            await session.commit()

    return {"ok": True, "cancelled_in_process": cancelled_in_process}


@router.get("/{report_id}/viewpoints")
async def get_report_viewpoints(
    report_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Viewpoints persisted by this report's run.

    Reads agent_runs.state_out.viewpoint_ids written by the knowledge_writer
    node. Falls back to ingested_at-window + topic filter for legacy reports
    whose state_out doesn't carry the IDs.
    """
    report = (await session.execute(
        select(models.Report).where(models.Report.id == report_id)
    )).scalar_one_or_none()
    if not report:
        raise HTTPException(404, "report not found")

    # Pull viewpoint_ids from any knowledge_writer agent_run for this report.
    runs = (await session.execute(
        select(models.AgentRun)
        .where(
            models.AgentRun.report_id == report_id,
            models.AgentRun.graph_node == "knowledge_writer",
        )
        .order_by(models.AgentRun.id)
    )).scalars().all()
    vp_ids: list[int] = []
    for r in runs:
        out = r.state_out or {}
        for x in (out.get("viewpoint_ids") or []):
            if isinstance(x, int) and x not in vp_ids:
                vp_ids.append(x)

    stmt = (
        select(
            models.Viewpoint,
            models.Expert.id.label("expert_id"),
            models.Expert.name.label("expert_name"),
            models.Expert.name_zh.label("expert_name_zh"),
            models.Expert.bio.label("expert_bio"),
            models.Expert.affiliations.label("expert_affiliations"),
            models.Expert.profile_urls.label("expert_profile_urls"),
            models.Source.domain.label("source_domain"),
        )
        .join(models.Expert, models.Expert.id == models.Viewpoint.expert_id)
        .join(models.Source, models.Source.id == models.Viewpoint.source_id, isouter=True)
        .order_by(desc(models.Viewpoint.confidence), desc(models.Viewpoint.claim_when))
    )

    if vp_ids:
        stmt = stmt.where(models.Viewpoint.id.in_(vp_ids))
    else:
        # Legacy fallback: viewpoints ingested during this report's run window
        # AND tagged with one of the report's focus topics.
        if report.finished_at and report.created_at:
            stmt = stmt.where(
                models.Viewpoint.ingested_at >= report.created_at,
                models.Viewpoint.ingested_at <= report.finished_at,
            )
        if report.focus_topics:
            topic_ids = (await session.execute(
                select(models.Topic.id).where(models.Topic.name.in_(report.focus_topics))
            )).scalars().all()
            if topic_ids:
                stmt = stmt.where(
                    models.Viewpoint.id.in_(
                        select(models.ViewpointTopic.viewpoint_id)
                        .where(models.ViewpointTopic.topic_id.in_(topic_ids))
                    )
                )

    rows = (await session.execute(stmt)).all()

    # Topic membership in one query
    vid_list = [r.Viewpoint.id for r in rows]
    topic_map: dict[int, list[str]] = {}
    if vid_list:
        topic_rows = (await session.execute(
            select(models.ViewpointTopic.viewpoint_id, models.Topic.name)
            .join(models.Topic, models.Topic.id == models.ViewpointTopic.topic_id)
            .where(models.ViewpointTopic.viewpoint_id.in_(vid_list))
        )).all()
        for vid, tname in topic_rows:
            topic_map.setdefault(vid, []).append(tname)

    return [
        {
            **r.Viewpoint.model_dump(),
            "expert_id": r.expert_id,
            "expert_name": r.expert_name,
            "expert_name_zh": r.expert_name_zh,
            "expert_role": r.expert_bio,
            "expert_affiliations": r.expert_affiliations,
            "expert_profile_urls": r.expert_profile_urls,
            "source_domain": r.source_domain,
            "topics": topic_map.get(r.Viewpoint.id, []),
        }
        for r in rows
    ]


@router.get("/{report_id}/search-results")
async def get_report_search_results(
    report_id: int,
    provider: str | None = None,
    limit: int | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Raw web_search / web_fetch hits for this report. No default limit —
    returning everything we have so the UI can show actual progress instead
    of the count plateauing at an artificial cap."""
    stmt = (
        select(models.SearchHit)
        .where(models.SearchHit.report_id == report_id)
        .order_by(desc(models.SearchHit.created_at))
    )
    if provider:
        stmt = stmt.where(models.SearchHit.provider == provider)
    if limit and limit > 0:
        stmt = stmt.limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    return rows
