"""Reports endpoints."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.runner import run_report
from app.db import models
from app.db.session import get_session
from app.schemas.api import CreateReportRequest

router = APIRouter(prefix="/api/reports", tags=["reports"])

# Strong refs to in-flight tasks so they aren't GC'd; cleaned via done-callback.
_BG_TASKS: set[asyncio.Task] = set()


def _spawn(coro) -> asyncio.Task:
    t = asyncio.create_task(coro)
    _BG_TASKS.add(t)
    t.add_done_callback(_BG_TASKS.discard)
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
    row = models.Report(
        title=payload.title,
        focus_topics=payload.focus_topics,
        time_range_start=_naive_utc(payload.time_range_start),
        time_range_end=_naive_utc(payload.time_range_end),
        md_template_id=payload.md_template_id,
        outline_template_id=payload.outline_template_id,
        providers_enabled=payload.providers_enabled,
        max_reflection_rounds=payload.max_reflection_rounds,
        cost_cap_usd=payload.cost_cap_usd,
        status=models.ReportStatus.pending,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)

    _spawn(run_report(row.id))
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
