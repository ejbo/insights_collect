"""CLI: smoke-test all enabled providers in one go.

Usage (inside Docker):
    docker exec insights-backend python -m app.tools.smoke
    docker exec insights-backend python -m app.tools.smoke --query "Token 经济" --lang zh

Prints a result table; exit code 0 if any provider succeeded, 1 otherwise.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

from app.config import get_settings
from app.db.session import SessionLocal
from app.providers.base import TimeRange
from app.providers.registry import build_providers


async def _run(query: str, lang: str, days: int, max_results: int) -> int:
    timeout_s = get_settings().smoke_call_timeout_s
    async with SessionLocal() as session:
        providers = await build_providers(session)
    if not providers:
        print("no enabled providers — configure keys in /settings", file=sys.stderr)
        return 1

    tw = TimeRange.last_n_days(days)
    print(f"Smoke testing {len(providers)} providers · query={query!r} · lang={lang} "
          f"· days={days} · timeout={timeout_s}s")
    print("─" * 110)
    print(f"{'provider':<12}{'success':<9}{'snippets':<10}{'tokens':<10}"
          f"{'cost($)':<10}{'latency(ms)':<13}{'error':<40}")
    print("─" * 110)

    any_ok = False
    tasks = []
    for name, prov in providers.items():
        tasks.append((name, prov))

    async def one(name, prov):
        t0 = time.perf_counter()
        try:
            r = await asyncio.wait_for(
                prov.search(query, tw, lang=lang, max_results=max_results),
                timeout=timeout_s,
            )
            tokens = (r.trace.tokens_input or 0) + (r.trace.tokens_output or 0)
            return name, r.trace.success, len(r.snippets), tokens, r.trace.cost_usd, \
                r.trace.latency_ms, r.trace.error or ""
        except asyncio.TimeoutError:
            ms = int((time.perf_counter() - t0) * 1000)
            return name, False, 0, 0, 0.0, ms, f"timeout({timeout_s}s)"
        except Exception as e:  # noqa: BLE001
            ms = int((time.perf_counter() - t0) * 1000)
            return name, False, 0, 0, 0.0, ms, str(e)[:38]

    results = await asyncio.gather(*[one(n, p) for n, p in tasks])
    for name, ok, snips, tokens, cost, latency, err in results:
        if ok:
            any_ok = True
        flag = "✓" if ok else "✗"
        print(f"{name:<12}{flag:<9}{snips:<10}{tokens:<10}{cost:<10.4f}{latency:<13}{err[:38]:<40}")
    print("─" * 110)
    return 0 if any_ok else 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", default="近期 AI 行业重要专家观点")
    ap.add_argument("--lang", default="zh", choices=["zh", "en", "mixed"])
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--max-results", type=int, default=5)
    args = ap.parse_args()
    code = asyncio.run(_run(args.query, args.lang, args.days, args.max_results))
    sys.exit(code)


if __name__ == "__main__":
    main()
