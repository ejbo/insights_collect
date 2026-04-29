"""KnowledgeWriter — persist experts / events / sources / viewpoints to DB.

This is what makes accumulation happen. Every report run grows the knowledge base.
"""

from __future__ import annotations

import logging
from datetime import datetime
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import ReportState
from app.db import models
from app.db.session import SessionLocal

log = logging.getLogger(__name__)


def _domain(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return (urlparse(url).hostname or "").lower().lstrip("www.")
    except Exception:  # noqa: BLE001
        return None


async def _ensure_expert(session: AsyncSession, name: str, role: str | None) -> models.Expert:
    if not name:
        raise ValueError("expert name required")
    row = (await session.execute(
        select(models.Expert).where(models.Expert.name == name)
    )).scalar_one_or_none()
    if row:
        if role and not row.bio:
            row.bio = role
        return row
    row = models.Expert(name=name, name_zh=name if any('一' <= c <= '鿿' for c in name) else None, bio=role)
    session.add(row)
    await session.flush()
    return row


async def _ensure_event(session: AsyncSession, name: str | None) -> models.Event | None:
    if not name:
        return None
    row = (await session.execute(
        select(models.Event).where(models.Event.name == name)
    )).scalar_one_or_none()
    if row:
        return row
    row = models.Event(name=name)
    session.add(row)
    await session.flush()
    return row


async def _ensure_source(session: AsyncSession, url: str | None) -> models.Source | None:
    domain = _domain(url)
    if not domain:
        return None
    row = (await session.execute(
        select(models.Source).where(models.Source.domain == domain)
    )).scalar_one_or_none()
    if row:
        return row
    row = models.Source(domain=domain, name=domain)
    session.add(row)
    await session.flush()
    return row


async def _ensure_topic(session: AsyncSession, name: str) -> models.Topic:
    slug = name.strip().lower().replace(" ", "-")[:64]
    row = (await session.execute(
        select(models.Topic).where(models.Topic.slug == slug)
    )).scalar_one_or_none()
    if row:
        return row
    row = models.Topic(slug=slug, name=name)
    session.add(row)
    await session.flush()
    return row


async def knowledge_writer_node(state: ReportState) -> dict:
    extracted = state.get("extracted_viewpoints") or []
    if not extracted:
        return {
            "persisted_expert_ids": [],
            "persisted_event_ids": [],
            "persisted_viewpoint_ids": [],
            "notes": ["knowledge_writer: nothing to persist"],
        }

    expert_ids: list[int] = []
    event_ids: list[int] = []
    viewpoint_ids: list[int] = []

    discovered_events = state.get("discovered_event_names") or []

    async with SessionLocal() as session:
        # Pre-create discovered events
        for ev_name in discovered_events:
            ev = await _ensure_event(session, ev_name)
            if ev and ev.id and ev.id not in event_ids:
                event_ids.append(ev.id)

        # Topic ensure
        topic_objs: dict[str, models.Topic] = {}
        for t in (state.get("focus_topics") or []):
            topic_objs[t] = await _ensure_topic(session, t)

        for v in extracted:
            try:
                expert = await _ensure_expert(session, v.expert_name, v.expert_role)
                event = await _ensure_event(session, v.claim_medium or v.claim_where)
                source = await _ensure_source(session, v.claim_source_url)

                vp = models.Viewpoint(
                    expert_id=expert.id,
                    event_id=event.id if event else None,
                    source_id=source.id if source else None,
                    claim_who_role=v.expert_role,
                    claim_when=v.claim_when,
                    claim_where=v.claim_where,
                    claim_what=v.claim_what,
                    claim_quote=v.claim_quote,
                    claim_medium=v.claim_medium,
                    claim_source_url=v.claim_source_url,
                    claim_why_context=v.claim_why_context,
                    claim_lang=v.claim_lang,
                    confidence=v.confidence,
                    providers_seen=None,
                    ingested_at=datetime.utcnow(),
                )
                session.add(vp)
                await session.flush()
                viewpoint_ids.append(vp.id)
                if expert.id and expert.id not in expert_ids:
                    expert_ids.append(expert.id)
                if event and event.id and event.id not in event_ids:
                    event_ids.append(event.id)

                # link to all focus topics (best-effort)
                for t_obj in topic_objs.values():
                    session.add(models.ViewpointTopic(viewpoint_id=vp.id, topic_id=t_obj.id, relevance=0.7))
            except Exception as e:  # noqa: BLE001
                log.exception("persist viewpoint failed: %s", e)

        await session.commit()

    return {
        "persisted_expert_ids": expert_ids,
        "persisted_event_ids": event_ids,
        "persisted_viewpoint_ids": viewpoint_ids,
        "notes": [
            f"knowledge_writer: persisted {len(viewpoint_ids)} viewpoints, "
            f"{len(expert_ids)} experts, {len(event_ids)} events"
        ],
    }
