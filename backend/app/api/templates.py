"""Report templates CRUD."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import models
from app.db.session import get_session
from app.schemas.api import TemplateUpsert

router = APIRouter(prefix="/api/templates", tags=["templates"])


@router.get("")
async def list_templates(
    kind: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    q = select(models.ReportTemplate)
    if kind:
        q = q.where(models.ReportTemplate.kind == kind)
    rows = (await session.execute(q.order_by(models.ReportTemplate.id))).scalars().all()
    return rows


@router.get("/{template_id}")
async def get_template(template_id: int, session: AsyncSession = Depends(get_session)):
    row = (await session.execute(
        select(models.ReportTemplate).where(models.ReportTemplate.id == template_id)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "template not found")
    return row


@router.post("")
async def create_template(payload: TemplateUpsert, session: AsyncSession = Depends(get_session)):
    row = models.ReportTemplate(
        name=payload.name,
        kind=payload.kind,
        prompt_template=payload.prompt_template,
        description=payload.description,
        jinja_vars=payload.jinja_vars,
        is_default=payload.is_default,
        is_builtin=False,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


@router.put("/{template_id}")
async def update_template(
    template_id: int, payload: TemplateUpsert, session: AsyncSession = Depends(get_session)
):
    row = (await session.execute(
        select(models.ReportTemplate).where(models.ReportTemplate.id == template_id)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "template not found")
    row.name = payload.name
    row.kind = payload.kind
    row.prompt_template = payload.prompt_template
    row.description = payload.description
    row.jinja_vars = payload.jinja_vars
    row.is_default = payload.is_default
    row.version += 1
    row.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(row)
    return row


@router.delete("/{template_id}")
async def delete_template(template_id: int, session: AsyncSession = Depends(get_session)):
    row = (await session.execute(
        select(models.ReportTemplate).where(models.ReportTemplate.id == template_id)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "template not found")
    if row.is_builtin:
        raise HTTPException(400, "built-in templates cannot be deleted")
    await session.delete(row)
    await session.commit()
    return {"status": "deleted", "id": template_id}
