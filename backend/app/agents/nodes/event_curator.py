"""EventCurator — LLM-driven cleanup of the global Event table.

Why this exists:
  knowledge_writer creates one Event row per distinct (claim_medium | claim_where)
  string the viewpoint extractor produces. The LLM frequently outputs generic
  content-type strings ("研究报告", "LinkedIn Post", "文章") instead of named
  events, polluting the /events tab. It also doesn't know that the same real
  event might appear under several spellings ("中国发展高层论坛 2025" vs
  "China Development Forum 2025") across different report runs.

What this does:
  Pulls every Event currently in the DB (or the current report's events when
  invoked from the pipeline), asks the main model to classify each one as
  keep / delete / merge_into:<canonical_id>, and applies the verdicts:
    - delete   → NULL out viewpoint.event_id, drop the Event row
    - merge    → repoint viewpoints to the canonical Event, drop the dupe
    - keep     → optionally enrich (kind, host, date) inferred from the name

Runs as the final pipeline node (after knowledge_writer) so users see a clean
list when they look at /events, and is also exposed as a one-shot HTTP endpoint
for ad-hoc cleanup of historical junk.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.main_model import pick_main_model
from app.agents.state import ReportState
from app.db import models
from app.db.session import SessionLocal
from app.providers.registry import build_providers
from app.schemas.llm import CuratorOutput, EventDecision

log = logging.getLogger(__name__)

_PROMPT = """你是知识图谱里 **events** 表的清洁工。下方是一组事件 (Event) 行，
每行带 id / 当前名称 / 关联观点数。请逐行判断：

1. **delete** — 名称是泛化内容类型而非具体事件，例如"研究报告"、"文章"、
   "LinkedIn Post"、"推文"、"采访"（无主语）、"博客"、"论坛"（无名字）。
   这些不是真实事件，应当删除。
2. **merge** — 与列表中另一行指代同一真实事件（不同语言、缩写、年份变体等）。
   填 `merge_into_id` 指向你认为最规范的那一条。
3. **keep** — 是真实的、可识别的具名事件 / 论坛 / 播客 / 文章 / 演讲。
   可以顺便补全 canonical_name / kind / host / date_iso（仅当你确实知道，
   否则留空，不要瞎编）。

注意：
- 若两条 "merge" 互相指向，下游会取保留观点数最多者；不必担心环。
- 同一具名事件每年一次的（如「中国发展高层论坛 2024」vs「2025」）属于
  **不同事件**，不要 merge。
- kind 必须从 {{forum, interview, podcast, keynote, paper, article, blog, other}} 选。

输出 JSON 必须为每个输入 id 各给一个 EventDecision。

事件列表：
{events_block}
"""


def _format_events(events: list[dict]) -> str:
    lines = []
    for e in events:
        host = f" · 主办: {e['host']}" if e.get("host") else ""
        url = f" · {e['url']}" if e.get("url") else ""
        date = f" · {e['date'][:10]}" if e.get("date") else ""
        lines.append(
            f"[{e['id']}] kind={e['kind']} viewpoints={e['viewpoint_count']}{host}{date}{url}\n"
            f"    name: {e['name']}"
        )
    return "\n".join(lines)


async def _load_events(
    session: AsyncSession,
    only_ids: list[int] | None = None,
) -> list[dict]:
    """Fetch (event, viewpoint_count) for the LLM to inspect."""
    from sqlalchemy import func

    vp_count = (
        select(
            models.Viewpoint.event_id.label("eid"),
            func.count(models.Viewpoint.id).label("n"),
        )
        .where(models.Viewpoint.event_id.is_not(None))
        .group_by(models.Viewpoint.event_id)
        .subquery()
    )
    stmt = (
        select(models.Event, func.coalesce(vp_count.c.n, 0).label("n"))
        .join(vp_count, vp_count.c.eid == models.Event.id, isouter=True)
        .order_by(models.Event.id)
    )
    if only_ids:
        stmt = stmt.where(models.Event.id.in_(only_ids))
    rows = (await session.execute(stmt)).all()
    return [
        {
            "id": r.Event.id,
            "name": r.Event.name,
            "kind": r.Event.kind.value if hasattr(r.Event.kind, "value") else str(r.Event.kind),
            "host": r.Event.host,
            "date": r.Event.date.isoformat() if r.Event.date else None,
            "url": r.Event.url,
            "viewpoint_count": int(r.n or 0),
        }
        for r in rows
    ]


async def _apply_decisions(
    session: AsyncSession,
    decisions: list[EventDecision],
    known_ids: set[int],
) -> dict:
    """Apply curator verdicts. Returns counts for logging.

    Order matters: do all merges first (so deletes can be cascaded safely),
    then deletes. Self-merge or merge-to-unknown is treated as keep.
    """
    by_id: dict[int, EventDecision] = {d.event_id: d for d in decisions if d.event_id in known_ids}

    # Resolve merge chains: A → B → C should land on C. Cap at 5 hops.
    def resolve_target(start: int) -> int | None:
        seen = {start}
        cur = start
        for _ in range(5):
            d = by_id.get(cur)
            if not d or d.action != "merge" or not d.merge_into_id:
                return cur if cur != start else None
            if d.merge_into_id in seen or d.merge_into_id not in known_ids:
                return None
            seen.add(d.merge_into_id)
            cur = d.merge_into_id
        return cur

    merged = 0
    deleted = 0
    kept = 0
    enriched = 0

    # Process in three passes so we never FK-violate: merges first (their
    # targets must still exist), then deletes (which null out viewpoints),
    # then keeps (enrich only — no row movement).
    for d in decisions:
        if d.event_id not in known_ids or d.action != "merge":
            continue
        target = resolve_target(d.event_id)
        if target is None or target == d.event_id:
            continue
        await session.execute(
            update(models.Viewpoint)
            .where(models.Viewpoint.event_id == d.event_id)
            .values(event_id=target)
        )
        await session.execute(
            models.Event.__table__.delete().where(models.Event.id == d.event_id)
        )
        merged += 1

    for d in decisions:
        if d.event_id not in known_ids or d.action != "delete":
            continue
        await session.execute(
            update(models.Viewpoint)
            .where(models.Viewpoint.event_id == d.event_id)
            .values(event_id=None)
        )
        await session.execute(
            models.Event.__table__.delete().where(models.Event.id == d.event_id)
        )
        deleted += 1

    for d in decisions:
        if d.event_id not in known_ids or d.action != "keep":
            continue
        row = (await session.execute(
            select(models.Event).where(models.Event.id == d.event_id)
        )).scalar_one_or_none()
        if row is None:
            continue
        kept += 1
        changed = False
        if d.canonical_name and d.canonical_name.strip() and d.canonical_name != row.name:
            row.name = d.canonical_name.strip()
            changed = True
        if d.kind and (not row.kind or row.kind == models.EventKind.other):
            try:
                row.kind = models.EventKind(d.kind)
                changed = True
            except ValueError:
                pass
        if d.host and not row.host:
            row.host = d.host
            changed = True
        if d.date_iso and not row.date:
            try:
                row.date = datetime.fromisoformat(d.date_iso.replace("Z", "+00:00"))
                if row.date.tzinfo is not None:
                    row.date = row.date.replace(tzinfo=None)
                changed = True
            except ValueError:
                pass
        if changed:
            enriched += 1

    await session.commit()
    return {"merged": merged, "deleted": deleted, "kept": kept, "enriched": enriched}


async def curate_events(
    *,
    state: ReportState | None = None,
    only_ids: list[int] | None = None,
) -> dict:
    """Core curation. Used by both the pipeline node (state passed) and the
    one-shot HTTP endpoint (state=None, all events considered)."""
    async with SessionLocal() as session:
        events = await _load_events(session, only_ids=only_ids)
        if not events:
            return {
                "events_considered": 0,
                "merged": 0, "deleted": 0, "kept": 0, "enriched": 0,
                "notes": "event_curator: no events to curate",
            }

        providers = await build_providers(session)
        chosen, main_model_id = pick_main_model(providers, state or {})
        if chosen is None:
            return {
                "events_considered": len(events),
                "merged": 0, "deleted": 0, "kept": 0, "enriched": 0,
                "errors": ["event_curator: no main_model provider configured"],
            }

        prompt = _PROMPT.format(events_block=_format_events(events))
        try:
            result = await chosen.structured_extract(
                prompt, CuratorOutput, model=main_model_id,
            )
        except Exception as e:  # noqa: BLE001
            log.exception("event curation LLM call failed")
            return {
                "events_considered": len(events),
                "merged": 0, "deleted": 0, "kept": 0, "enriched": 0,
                "errors": [f"event_curator failed: {e}"],
            }

        out: CuratorOutput = result.data  # type: ignore[assignment]
        known_ids = {e["id"] for e in events}
        applied = await _apply_decisions(session, out.decisions, known_ids)

        return {
            "events_considered": len(events),
            **applied,
            "trace": result.trace,
            "decisions": [d.model_dump() for d in out.decisions],
        }


async def event_curator_node(state: ReportState) -> dict:
    """Pipeline wrapper — runs after knowledge_writer.

    Curates the FULL global event table (not just this report's events) so
    cross-report duplicates collapse on every run. Cheap because most events
    are already curated; the LLM mostly just emits 'keep' for them.
    """
    res = await curate_events(state=state)
    note = (
        f"event_curator: 处理 {res['events_considered']} 个事件 → "
        f"删 {res.get('deleted', 0)} · 合并 {res.get('merged', 0)} · "
        f"保留 {res.get('kept', 0)} (其中补全 {res.get('enriched', 0)})"
    )
    out = {
        "notes": [note],
        "errors": res.get("errors") or [],
    }
    if res.get("trace"):
        t = res["trace"]
        out["provider_traces"] = [t]
        out["total_cost_usd"] = t.cost_usd
        out["total_tokens"] = (t.tokens_input or 0) + (t.tokens_output or 0)
    return out
