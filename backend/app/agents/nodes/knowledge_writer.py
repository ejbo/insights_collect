"""KnowledgeWriter — persist experts / events / sources / viewpoints to DB.

This is what makes accumulation happen. Every report run grows the knowledge base.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import ReportState
from app.db import models
from app.db.session import SessionLocal

log = logging.getLogger(__name__)


def _naive_utc(dt: datetime | None) -> datetime | None:
    """DB columns are TIMESTAMP WITHOUT TIME ZONE; coerce aware → naive UTC."""
    if dt is None or dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _domain(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return (urlparse(url).hostname or "").lower().lstrip("www.")
    except Exception:  # noqa: BLE001
        return None


def _is_zh(name: str) -> bool:
    return any('一' <= c <= '鿿' for c in name)


def _merge_unique(existing: list | None, new: list | None) -> list | None:
    """Union of two list[str] preserving order; returns None if both empty."""
    out: list[str] = []
    seen = set()
    for src in (existing or []), (new or []):
        for x in src:
            if x and x not in seen:
                seen.add(x)
                out.append(x)
    return out or None


async def _ensure_expert(
    session: AsyncSession,
    *,
    name: str,
    name_zh: str | None = None,
    role: str | None = None,
    affiliations: list[str] | None = None,
    profile_urls: list[str] | None = None,
    domains: list[str] | None = None,
) -> models.Expert:
    if not name:
        raise ValueError("expert name required")
    row = (await session.execute(
        select(models.Expert).where(models.Expert.name == name)
    )).scalar_one_or_none()
    if row:
        # Best-effort merge — never overwrite richer existing data with thinner info.
        if role and not row.bio:
            row.bio = role
        if name_zh and not row.name_zh:
            row.name_zh = name_zh
        elif _is_zh(name) and not row.name_zh:
            row.name_zh = name
        merged_aff = _merge_unique(row.affiliations, affiliations)
        if merged_aff:
            row.affiliations = merged_aff
        merged_urls = _merge_unique(row.profile_urls, profile_urls)
        if merged_urls:
            row.profile_urls = merged_urls
        merged_dom = _merge_unique(row.domains, domains)
        if merged_dom:
            row.domains = merged_dom
        row.updated_at = datetime.utcnow()
        return row
    row = models.Expert(
        name=name,
        name_zh=name_zh or (name if _is_zh(name) else None),
        bio=role,
        affiliations=affiliations or None,
        profile_urls=profile_urls or None,
        domains=domains or None,
    )
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
    expert_candidates = state.get("expert_candidates") or []

    async with SessionLocal() as session:
        # Pre-create discovered events
        for ev_name in discovered_events:
            ev = await _ensure_event(session, ev_name)
            if ev and ev.id and ev.id not in event_ids:
                event_ids.append(ev.id)

        # Pre-create / enrich expert candidates with full discovered metadata.
        # The viewpoint loop later will ensure-by-name and merge into the same
        # rows, so we don't lose any of the rationale / affiliations the model
        # gave us at discovery time.
        for cand in expert_candidates:
            try:
                async with session.begin_nested():
                    ex = await _ensure_expert(
                        session,
                        name=cand.name,
                        name_zh=cand.name_zh,
                        role=cand.role,
                        affiliations=cand.affiliations or None,
                        profile_urls=cand.profile_urls or None,
                    )
                    if ex.id and ex.id not in expert_ids:
                        expert_ids.append(ex.id)
            except Exception as e:  # noqa: BLE001
                log.warning("upsert expert candidate %s failed: %s", cand.name, e)

        # Topic ensure
        topic_objs: dict[str, models.Topic] = {}
        for t in (state.get("focus_topics") or []):
            topic_objs[t] = await _ensure_topic(session, t)

        for v in extracted:
            try:
                # Savepoint per viewpoint — a single bad row (bad URL, FK miss,
                # invalid timestamp) cannot abort the whole transaction.
                async with session.begin_nested():
                    expert = await _ensure_expert(
                        session, name=v.expert_name, role=v.expert_role,
                    )
                    event = await _ensure_event(session, v.claim_medium or v.claim_where)
                    source = await _ensure_source(session, v.claim_source_url)

                    vp = models.Viewpoint(
                        expert_id=expert.id,
                        event_id=event.id if event else None,
                        source_id=source.id if source else None,
                        claim_who_role=v.expert_role,
                        claim_when=_naive_utc(v.claim_when),
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

                    for t_obj in topic_objs.values():
                        session.add(models.ViewpointTopic(viewpoint_id=vp.id, topic_id=t_obj.id, relevance=0.7))
            except Exception as e:  # noqa: BLE001
                log.warning("persist viewpoint failed (skipped): %s", e)

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
