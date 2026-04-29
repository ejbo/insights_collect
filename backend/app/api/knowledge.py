"""Read-only views over experts / events / sources / topics / viewpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import models
from app.db.session import get_session

router = APIRouter(prefix="/api", tags=["knowledge"])


@router.get("/experts")
async def list_experts(
    q: str | None = None,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
):
    stmt = select(models.Expert)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            (models.Expert.name.ilike(like)) | (models.Expert.name_zh.ilike(like))
        )
    stmt = stmt.order_by(desc(models.Expert.updated_at)).limit(limit)
    return (await session.execute(stmt)).scalars().all()


@router.get("/experts/{expert_id}")
async def get_expert(expert_id: int, session: AsyncSession = Depends(get_session)):
    row = (await session.execute(
        select(models.Expert).where(models.Expert.id == expert_id)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(404)
    return row


@router.get("/experts/{expert_id}/viewpoints")
async def expert_viewpoints(expert_id: int, session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(
        select(models.Viewpoint)
        .where(models.Viewpoint.expert_id == expert_id)
        .order_by(desc(models.Viewpoint.claim_when))
    )).scalars().all()
    return rows


@router.get("/events")
async def list_events(limit: int = 100, session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(
        select(models.Event).order_by(desc(models.Event.created_at)).limit(limit)
    )).scalars().all()
    return rows


@router.get("/sources")
async def list_sources(limit: int = 100, session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(
        select(models.Source).order_by(models.Source.domain).limit(limit)
    )).scalars().all()
    return rows


@router.get("/topics")
async def list_topics(session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(models.Topic).order_by(models.Topic.id))).scalars().all()
    return rows


@router.get("/viewpoints")
async def list_viewpoints(
    topic: str | None = None,
    expert: str | None = None,
    limit: int = 100,
    session: AsyncSession = Depends(get_session),
):
    stmt = select(models.Viewpoint).order_by(desc(models.Viewpoint.ingested_at)).limit(limit)
    if expert:
        sub = select(models.Expert.id).where(
            (models.Expert.name == expert) | (models.Expert.name_zh == expert)
        )
        stmt = stmt.where(models.Viewpoint.expert_id.in_(sub))
    rows = (await session.execute(stmt)).scalars().all()
    if topic and rows:
        # Best-effort filter by topic name via viewpoint_topics join
        topic_row = (await session.execute(
            select(models.Topic).where(models.Topic.name == topic)
        )).scalar_one_or_none()
        if topic_row:
            ids = (await session.execute(
                select(models.ViewpointTopic.viewpoint_id)
                .where(models.ViewpointTopic.topic_id == topic_row.id)
            )).scalars().all()
            rows = [r for r in rows if r.id in set(ids)]
    return rows


@router.get("/stats")
async def stats(session: AsyncSession = Depends(get_session)):
    expert_count = (await session.execute(select(func.count(models.Expert.id)))).scalar() or 0
    viewpoint_count = (await session.execute(select(func.count(models.Viewpoint.id)))).scalar() or 0
    event_count = (await session.execute(select(func.count(models.Event.id)))).scalar() or 0
    source_count = (await session.execute(select(func.count(models.Source.id)))).scalar() or 0
    topic_count = (await session.execute(select(func.count(models.Topic.id)))).scalar() or 0
    report_count = (await session.execute(select(func.count(models.Report.id)))).scalar() or 0
    return {
        "experts": expert_count,
        "viewpoints": viewpoint_count,
        "events": event_count,
        "sources": source_count,
        "topics": topic_count,
        "reports": report_count,
    }
