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
from app.schemas.api import ProviderCredentialUpdate, ProviderCredentialView

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _to_view(row: models.ProviderCredential) -> ProviderCredentialView:
    return ProviderCredentialView(
        provider=row.provider,
        has_key=bool(row.api_key),
        base_url=row.base_url,
        default_model=row.default_model,
        enabled=row.enabled,
        last_tested_at=row.last_tested_at,
        test_status=row.test_status,
        test_message=row.test_message,
    )


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
        # Create on the fly (so /settings can self-heal if seed missed)
        row = models.ProviderCredential(provider=provider, api_key="")
        session.add(row)

    if payload.api_key is not None:
        row.api_key = payload.api_key
    if payload.base_url is not None:
        row.base_url = payload.base_url or None
    if payload.default_model is not None:
        row.default_model = payload.default_model or None
    if payload.enabled is not None:
        row.enabled = payload.enabled
    row.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(row)
    return _to_view(row)


class SmokeRequest(BaseModel):
    query: str = Field(default="近期 AI 行业重要专家观点")
    lang: str = Field(default="zh")
    days: int = Field(default=30, ge=1, le=180)
    max_results: int = Field(default=5, ge=1, le=20)


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

    t0 = time.perf_counter()
    try:
        result = await asyncio.wait_for(
            client.search(payload.query, tw, lang=payload.lang, max_results=payload.max_results),
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
        trace = await client.health_check()
        if trace.success:
            row.test_status = "ok"
            row.test_message = f"{trace.provider}/{trace.model} latency={trace.latency_ms}ms"
        else:
            row.test_status = "error"
            row.test_message = trace.error or "unknown error"
    except Exception as e:  # noqa: BLE001
        row.test_status = "error"
        row.test_message = str(e)
    row.last_tested_at = datetime.utcnow()
    await session.commit()
    await session.refresh(row)
    return _to_view(row)
