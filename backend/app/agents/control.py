"""Per-report control flags shared between the API and the running graph.

Currently only `advance_event` — the user can press 「立即进入下一步」 to tell
the running multi_search node to stop dispatching and continue with whatever
results have already arrived. Lives in process memory because the graph runner
runs in-process; if the API process restarts, the in-flight task is gone too.
"""

from __future__ import annotations

import asyncio

_advance_events: dict[int, asyncio.Event] = {}


def get_advance_event(report_id: int) -> asyncio.Event:
    ev = _advance_events.get(report_id)
    if ev is None:
        ev = asyncio.Event()
        _advance_events[report_id] = ev
    return ev


def request_advance(report_id: int) -> None:
    get_advance_event(report_id).set()


def is_advance_requested(report_id: int) -> bool:
    ev = _advance_events.get(report_id)
    return bool(ev and ev.is_set())


def clear(report_id: int) -> None:
    _advance_events.pop(report_id, None)
