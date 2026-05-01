"""Provider credentials CRUD + connection test + smoke-test full search."""

import asyncio
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import models
from app.db.session import get_session
from app.providers.base import TimeRange
from app.providers.registry import _FACTORY  # internal — purely for instantiating a single test client
from app.schemas.api import (
    BulkProviderUpdate,
    ProviderCredentialUpdate,
    ProviderCredentialView,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _to_view(row: models.ProviderCredential) -> ProviderCredentialView:
    return ProviderCredentialView(
        provider=row.provider,
        api_key=row.api_key or "",
        has_key=bool(row.api_key),
        base_url=row.base_url,
        default_model=row.default_model,
        enabled=row.enabled,
        last_tested_at=row.last_tested_at,
        test_status=row.test_status,
        test_message=row.test_message,
    )


def _apply_update(row: models.ProviderCredential, *,
                  api_key: str | None, base_url: str | None,
                  default_model: str | None) -> None:
    """In-place mutate row from optional patch fields. Auto-enables when key set."""
    if api_key is not None:
        row.api_key = api_key
        row.enabled = bool(api_key)  # auto-enable when key set, auto-disable when cleared
    if base_url is not None:
        row.base_url = base_url or None
    if default_model is not None:
        row.default_model = default_model or None
    row.updated_at = datetime.utcnow()


@router.get("/providers", response_model=list[ProviderCredentialView])
async def list_provider_credentials(session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(
        select(models.ProviderCredential).order_by(models.ProviderCredential.id)
    )).scalars().all()
    return [_to_view(r) for r in rows]


@router.put("/providers/{provider}", response_model=ProviderCredentialView)
async def update_provider_credentials(
    provider: str,
    payload: ProviderCredentialUpdate,
    session: AsyncSession = Depends(get_session),
):
    row = (await session.execute(
        select(models.ProviderCredential).where(models.ProviderCredential.provider == provider)
    )).scalar_one_or_none()
    if not row:
        row = models.ProviderCredential(provider=provider, api_key="")
        session.add(row)

    _apply_update(
        row,
        api_key=payload.api_key,
        base_url=payload.base_url,
        default_model=payload.default_model,
    )
    if payload.enabled is not None:
        # Backwards-compat: explicit override still respected if sent.
        row.enabled = payload.enabled
    await session.commit()
    await session.refresh(row)
    return _to_view(row)


@router.put("/providers", response_model=list[ProviderCredentialView])
async def bulk_update_provider_credentials(
    payload: list[BulkProviderUpdate],
    session: AsyncSession = Depends(get_session),
):
    """Save many providers at once — used by /settings 'Save all' button."""
    by_provider = {p.provider: p for p in payload}
    rows = (await session.execute(
        select(models.ProviderCredential).where(
            models.ProviderCredential.provider.in_(list(by_provider.keys()))
        )
    )).scalars().all()
    existing = {r.provider: r for r in rows}

    out: list[models.ProviderCredential] = []
    for p in payload:
        row = existing.get(p.provider)
        if row is None:
            row = models.ProviderCredential(provider=p.provider, api_key="")
            session.add(row)
        _apply_update(row, api_key=p.api_key, base_url=p.base_url, default_model=p.default_model)
        out.append(row)
    await session.commit()
    for r in out:
        await session.refresh(r)
    return [_to_view(r) for r in out]


class SmokeRequest(BaseModel):
    query: str = Field(default="近期 AI 行业重要专家观点")
    lang: str = Field(default="zh")
    days: int = Field(default=30, ge=1, le=180)
    max_results: int = Field(default=5, ge=1, le=20)


# Minimal per-provider options for smoke tests — keeps the call under ~30s so
# Next.js dev-proxy doesn't drop the connection.
_SMOKE_OPTIONS: dict[str, dict] = {
    "anthropic": {
        "effort": "low",
        "max_uses": 2,
        "max_fetches": 0,
        "enable_web_search": True,
        "enable_web_fetch": False,
    },
    "gemini": {
        "thinking_budget": 0,        # disable thinking for speed
        "max_output_tokens": 1024,
        "enable_search": True,
        "max_search_queries": 2,
        "max_grounding_chunks": 5,
    },
    "qwen": {
        "enable_search": True,
        "enable_thinking": False,    # off for fast smoke test
        "search_strategy": "agent",
        "max_output_tokens": 1024,
    },
    "grok": {
        # Smoke test single-pass to keep latency tight. Dual-pass is the
        # production default but it doubles the call volume.
        "enable_dual_pass": False,
        "enable_image_understanding": False,
        "enable_video_understanding": False,
    },
}


class SmokeResult(BaseModel):
    success: bool
    duration_ms: int
    snippets_count: int
    sample: list[dict]
    trace: dict
    error: str | None = None


@router.post("/providers/{provider}/smoke", response_model=SmokeResult)
async def smoke_search(
    provider: str,
    payload: SmokeRequest = SmokeRequest(),
    session: AsyncSession = Depends(get_session),
):
    """Run a real provider.search() with a tight timeout. Confirms the provider's
    full search chain works (auth + network + parsing) — not just key validity.
    """
    row = (await session.execute(
        select(models.ProviderCredential).where(models.ProviderCredential.provider == provider)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "provider not found")
    if not row.api_key:
        raise HTTPException(400, "provider has no API key configured")
    factory = _FACTORY.get(provider)
    if factory is None:
        raise HTTPException(400, "unknown provider")

    timeout_s = get_settings().smoke_call_timeout_s
    client = factory(api_key=row.api_key, base_url=row.base_url, default_model=row.default_model)
    tw = TimeRange.last_n_days(payload.days)
    smoke_opts = _SMOKE_OPTIONS.get(provider)

    t0 = time.perf_counter()
    try:
        result = await asyncio.wait_for(
            client.search(
                payload.query, tw,
                lang=payload.lang,
                max_results=payload.max_results,
                options=smoke_opts,
            ),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        duration = int((time.perf_counter() - t0) * 1000)
        return SmokeResult(
            success=False, duration_ms=duration, snippets_count=0,
            sample=[], trace={"provider": provider, "error": f"timeout ({timeout_s}s)"},
            error=f"timeout after {timeout_s}s",
        )
    except Exception as e:  # noqa: BLE001
        duration = int((time.perf_counter() - t0) * 1000)
        return SmokeResult(
            success=False, duration_ms=duration, snippets_count=0,
            sample=[], trace={"provider": provider, "error": str(e)[:300]},
            error=str(e)[:300],
        )

    duration = int((time.perf_counter() - t0) * 1000)
    sample = [
        {
            "title": s.title,
            "url": s.url,
            "snippet": (s.snippet or "")[:300],
            "source_domain": s.source_domain,
        }
        for s in result.snippets[:5]
    ]
    return SmokeResult(
        success=result.trace.success,
        duration_ms=duration,
        snippets_count=len(result.snippets),
        sample=sample,
        trace={
            "provider": result.trace.provider,
            "model": result.trace.model,
            "tokens_input": result.trace.tokens_input,
            "tokens_output": result.trace.tokens_output,
            "cost_usd": result.trace.cost_usd,
            "latency_ms": result.trace.latency_ms,
        },
        error=result.trace.error,
    )


@router.post("/providers/{provider}/test", response_model=ProviderCredentialView)
async def test_provider(provider: str, session: AsyncSession = Depends(get_session)):
    """Cheap key validation — calls provider.quick_validate() with a 12s timeout.

    For most providers this is `GET /v1/models`-style: sub-second, no LLM tokens.
    Test message includes what was sent and a sample of the response so you can see
    exactly what the test did.
    """
    row = (await session.execute(
        select(models.ProviderCredential).where(models.ProviderCredential.provider == provider)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "provider not found")
    factory = _FACTORY.get(provider)
    if factory is None:
        raise HTTPException(400, "unknown provider")

    try:
        client = factory(api_key=row.api_key, base_url=row.base_url, default_model=row.default_model)
        trace = await asyncio.wait_for(client.quick_validate(), timeout=12.0)
        if trace.success:
            row.test_status = "ok"
            sent = trace.extra.get("sent") if trace.extra else None
            got = trace.extra.get("got") if trace.extra else None
            parts = [f"{trace.latency_ms}ms"]
            if sent: parts.append(f"sent: {sent}")
            if got: parts.append(f"got: {got[:120]}")
            row.test_message = " · ".join(parts)
        else:
            row.test_status = "error"
            row.test_message = trace.error or "unknown error"
    except asyncio.TimeoutError:
        row.test_status = "error"
        row.test_message = "timeout (12s) — network issue or invalid base_url"
    except Exception as e:  # noqa: BLE001
        row.test_status = "error"
        row.test_message = str(e)[:300]
    row.last_tested_at = datetime.utcnow()
    await session.commit()
    await session.refresh(row)
    return _to_view(row)
