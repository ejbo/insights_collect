"""Read-only (and a few write) views over experts / events / sources / topics / viewpoints."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import models
from app.db.session import get_session

router = APIRouter(prefix="/api", tags=["knowledge"])


@router.get("/experts")
async def list_experts(
    q: str | None = None,
    sort: str = "viewpoints",  # viewpoints | recent | name
    limit: int = 200,
    session: AsyncSession = Depends(get_session),
):
    """Expert list with viewpoint count rolled up so the UI can sort meaningfully."""
    vp_count = (
        select(
            models.Viewpoint.expert_id.label("eid"),
            func.count(models.Viewpoint.id).label("vp_count"),
            func.max(models.Viewpoint.claim_when).label("last_claim_at"),
        )
        .group_by(models.Viewpoint.expert_id)
        .subquery()
    )

    stmt = (
        select(
            models.Expert,
            func.coalesce(vp_count.c.vp_count, 0).label("vp_count"),
            vp_count.c.last_claim_at,
        )
        .join(vp_count, vp_count.c.eid == models.Expert.id, isouter=True)
    )
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            (models.Expert.name.ilike(like)) | (models.Expert.name_zh.ilike(like))
        )
    if sort == "name":
        stmt = stmt.order_by(models.Expert.name.asc())
    elif sort == "recent":
        stmt = stmt.order_by(desc(vp_count.c.last_claim_at), desc(models.Expert.updated_at))
    else:  # viewpoints (default)
        stmt = stmt.order_by(desc("vp_count"), desc(models.Expert.updated_at))
    stmt = stmt.limit(limit)

    rows = (await session.execute(stmt)).all()
    return [
        {
            "id": r.Expert.id,
            "name": r.Expert.name,
            "name_zh": r.Expert.name_zh,
            "bio": r.Expert.bio,
            "affiliations": r.Expert.affiliations,
            "profile_urls": r.Expert.profile_urls,
            "domains": r.Expert.domains,
            "updated_at": r.Expert.updated_at,
            "viewpoint_count": int(r.vp_count or 0),
            "last_claim_at": r.last_claim_at,
        }
        for r in rows
    ]


@router.get("/experts/{expert_id}")
async def get_expert(expert_id: int, session: AsyncSession = Depends(get_session)):
    row = (await session.execute(
        select(models.Expert).where(models.Expert.id == expert_id)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(404)

    # roll-ups
    vp_count = (await session.execute(
        select(func.count(models.Viewpoint.id)).where(models.Viewpoint.expert_id == expert_id)
    )).scalar() or 0

    domain_rows = (await session.execute(
        select(
            models.Source.domain,
            func.count(models.Viewpoint.id).label("n"),
        )
        .join(models.Source, models.Source.id == models.Viewpoint.source_id)
        .where(models.Viewpoint.expert_id == expert_id)
        .group_by(models.Source.domain)
        .order_by(desc("n"))
        .limit(20)
    )).all()

    return {
        **row.model_dump(),
        "viewpoint_count": int(vp_count),
        "source_domains": [{"domain": r.domain, "count": int(r.n)} for r in domain_rows],
    }


class ExpertUpdate(BaseModel):
    name: str | None = None
    name_zh: str | None = None
    bio: str | None = None
    affiliations: list[str] | None = None
    profile_urls: list[str] | None = None
    domains: list[str] | None = None


@router.patch("/experts/{expert_id}")
async def update_expert(
    expert_id: int,
    payload: ExpertUpdate,
    session: AsyncSession = Depends(get_session),
):
    row = (await session.execute(
        select(models.Expert).where(models.Expert.id == expert_id)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "expert not found")
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and (data["name"] is None or data["name"].strip() == ""):
        raise HTTPException(400, "name must not be empty")
    for k, v in data.items():
        setattr(row, k, v)
    row.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(row)
    return row


@router.get("/experts/{expert_id}/viewpoints")
async def expert_viewpoints(expert_id: int, session: AsyncSession = Depends(get_session)):
    """All viewpoints (full 7-tuple) for one expert, joined with source domain
    so the UI can render where it was published."""
    stmt = (
        select(models.Viewpoint, models.Source.domain)
        .join(models.Source, models.Source.id == models.Viewpoint.source_id, isouter=True)
        .where(models.Viewpoint.expert_id == expert_id)
        .order_by(desc(models.Viewpoint.claim_when), desc(models.Viewpoint.ingested_at))
    )
    rows = (await session.execute(stmt)).all()
    return [
        {
            **r.Viewpoint.model_dump(),
            "source_domain": r.domain,
        }
        for r in rows
    ]


@router.get("/events")
async def list_events(limit: int = 200, session: AsyncSession = Depends(get_session)):
    """Events with viewpoint counts (so the UI can show 引用数 / 排序)."""
    vp_count = (
        select(
            models.Viewpoint.event_id.label("eid"),
            func.count(models.Viewpoint.id).label("vp_count"),
        )
        .where(models.Viewpoint.event_id.is_not(None))
        .group_by(models.Viewpoint.event_id)
        .subquery()
    )
    stmt = (
        select(
            models.Event,
            func.coalesce(vp_count.c.vp_count, 0).label("vp_count"),
        )
        .join(vp_count, vp_count.c.eid == models.Event.id, isouter=True)
        .order_by(desc("vp_count"), desc(models.Event.created_at))
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [
        {
            **r.Event.model_dump(),
            "viewpoint_count": int(r.vp_count or 0),
        }
        for r in rows
    ]


@router.get("/events/{event_id}")
async def get_event(event_id: int, session: AsyncSession = Depends(get_session)):
    """Event detail: metadata + every viewpoint under it (joined with expert
    name + source domain), distinct experts, and the focus_topics of every
    report whose run produced these viewpoints."""
    row = (await session.execute(
        select(models.Event).where(models.Event.id == event_id)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "event not found")

    vp_rows = (await session.execute(
        select(
            models.Viewpoint,
            models.Expert.id.label("expert_id"),
            models.Expert.name.label("expert_name"),
            models.Expert.name_zh.label("expert_name_zh"),
            models.Source.domain.label("source_domain"),
        )
        .join(models.Expert, models.Expert.id == models.Viewpoint.expert_id)
        .join(models.Source, models.Source.id == models.Viewpoint.source_id, isouter=True)
        .where(models.Viewpoint.event_id == event_id)
        .order_by(desc(models.Viewpoint.claim_when), desc(models.Viewpoint.ingested_at))
    )).all()

    viewpoints = [
        {
            **r.Viewpoint.model_dump(),
            "expert_id": r.expert_id,
            "expert_name": r.expert_name,
            "expert_name_zh": r.expert_name_zh,
            "source_domain": r.source_domain,
        }
        for r in vp_rows
    ]

    # Distinct experts (preserve order of first appearance).
    seen: set[int] = set()
    experts: list[dict] = []
    for v in viewpoints:
        eid = v["expert_id"]
        if eid in seen:
            continue
        seen.add(eid)
        experts.append({
            "id": eid,
            "name": v["expert_name"],
            "name_zh": v["expert_name_zh"],
            "viewpoint_count": sum(1 for x in viewpoints if x["expert_id"] == eid),
        })

    # Topics rolled up from viewpoint_topics.
    topic_rows = (await session.execute(
        select(models.Topic.name, func.count(models.ViewpointTopic.viewpoint_id).label("n"))
        .join(models.ViewpointTopic, models.ViewpointTopic.topic_id == models.Topic.id)
        .where(models.ViewpointTopic.viewpoint_id.in_([v["id"] for v in viewpoints]) if viewpoints else False)
        .group_by(models.Topic.name)
        .order_by(desc("n"))
    )).all() if viewpoints else []

    return {
        **row.model_dump(),
        "viewpoint_count": len(viewpoints),
        "experts": experts,
        "topics": [{"name": r.name, "count": int(r.n)} for r in topic_rows],
        "viewpoints": viewpoints,
    }


@router.post("/events/curate-now")
async def curate_events_now():
    """One-shot LLM curation across the global event table. Useful when the
    user wants to clean up historical junk without launching a new report."""
    from app.agents.nodes.event_curator import curate_events

    res = await curate_events()
    if res.get("trace"):
        res.pop("trace", None)  # not JSON-serialisable
    return res


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
    limit: int = 200,
    session: AsyncSession = Depends(get_session),
):
    """Enriched viewpoint list: joins expert name + source domain so the UI
    doesn't need an N+1 fan-out."""
    stmt = (
        select(
            models.Viewpoint,
            models.Expert.name.label("expert_name"),
            models.Expert.name_zh.label("expert_name_zh"),
            models.Source.domain.label("source_domain"),
        )
        .join(models.Expert, models.Expert.id == models.Viewpoint.expert_id)
        .join(models.Source, models.Source.id == models.Viewpoint.source_id, isouter=True)
        .order_by(desc(models.Viewpoint.claim_when), desc(models.Viewpoint.ingested_at))
        .limit(limit)
    )
    if expert:
        stmt = stmt.where(
            (models.Expert.name == expert) | (models.Expert.name_zh == expert)
        )
    if topic:
        topic_row = (await session.execute(
            select(models.Topic).where(models.Topic.name == topic)
        )).scalar_one_or_none()
        if topic_row:
            stmt = stmt.where(
                models.Viewpoint.id.in_(
                    select(models.ViewpointTopic.viewpoint_id)
                    .where(models.ViewpointTopic.topic_id == topic_row.id)
                )
            )

    rows = (await session.execute(stmt)).all()
    return [
        {
            **r.Viewpoint.model_dump(),
            "expert_name": r.expert_name,
            "expert_name_zh": r.expert_name_zh,
            "source_domain": r.source_domain,
        }
        for r in rows
    ]


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
