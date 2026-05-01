"""Report templates CRUD."""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import models
from app.db.session import get_session
from app.render.markdown_renderer import render_markdown
from app.render.ppt_outline_renderer import render_ppt_outline
from app.schemas.api import TemplateUpsert

router = APIRouter(prefix="/api/templates", tags=["templates"])


# Mock context used by /preview — mirrors exactly what report_composer builds at
# render time (see backend/app/agents/nodes/report_composer.py:_build_sections /
# :_viewpoints_for_render). Keep these shapes in sync if you add fields.
def _mock_ctx() -> dict:
    sample_vp = lambda name, role, what, quote=None, medium=None, where=None, when=None: {
        "expert_name": name,
        "claim_who_role": role,
        "claim_when": datetime.fromisoformat(when) if when else datetime(2026, 4, 12, 9, 30),
        "claim_where": where or "中国发展高层论坛 2026",
        "claim_what": what,
        "claim_quote": quote,
        "claim_medium": medium or "主旨发言",
        "claim_source_url": "https://example.com/article",
        "claim_why_context": "在产业升级与人口结构变化的双重背景下提出。",
        "source_domain": "example.com",
    }
    viewpoints = [
        sample_vp(
            "李未可", "国家数据局局长",
            "数据要素市场化要从公共数据开放破题，避免重复建设。",
            quote="公共数据是基础设施，不该有任何门槛地开放。",
        ),
        sample_vp(
            "Andrew Ng", "Stanford / Landing AI",
            "AI agent 的下一步是把 reasoning loops 做得更便宜更稳定。",
            quote="Cheaper reasoning unlocks orders of magnitude more agentic use cases.",
            where="Stanford HAI Symposium",
            medium="Keynote",
        ),
        sample_vp(
            "陈昊", "清华大学经管学院教授",
            "AI 投入对 TFP 的边际贡献仍未在统计口径上体现。",
        ),
    ]
    sections = [
        {
            "topic_name": "AI 治理与数据要素",
            "section_summary": "监管侧强调可解释；产业侧呼吁基础设施型公共数据开放。",
            "clusters": [
                {
                    "label": "公共数据应当无门槛开放",
                    "kind": "consensus",
                    "summary_md": "多位嘉宾认为公共数据是数字经济的基础设施，开放是前提。",
                    "viewpoints": viewpoints[:1],
                },
                {
                    "label": "对当前 LLM 真实生产力的乐观与谨慎",
                    "kind": "dissent",
                    "summary_md": "Ng 认为成本下降会指数级放大场景；陈昊认为 TFP 数据并未印证。",
                    "viewpoints": viewpoints[1:],
                },
            ],
        },
    ]
    analysis = {
        "executive_summary": "本期围绕 AI 治理与生产力议题，专家在公共数据开放上达成共识，"
                             "但对 AI 短期生产力贡献仍有显著分歧。",
        "executive_summary_bullets": [
            "公共数据开放被视为下一个基础设施级机会",
            "Reasoning loops 的成本下降决定了 agent 能力上限",
            "TFP 口径上 AI 贡献尚不显著，需关注实际产业链传导",
        ],
        "consensus": ["公共数据是数字经济的基础设施", "AI agent 是下一代生产力载体"],
        "dissent": ["AI 短期 TFP 贡献的乐观与保守之争"],
        "spotlight": ["陈昊提出统计口径滞后导致 AI 红利低估"],
        "insight": ["关注 reasoning 成本曲线，可能是 agent 普及的转折点"],
    }
    return {
        "title": "AI 治理与生产力周报 · 示例",
        "focus_topics": ["AI 治理", "AI 生产力"],
        "time_range_start": datetime(2026, 4, 23),
        "time_range_end": datetime(2026, 4, 30),
        "sections": sections,
        "analysis": analysis,
        "all_viewpoints": viewpoints,
        "top_viewpoints": viewpoints,
    }


class TemplatePreviewRequest(BaseModel):
    prompt_template: str
    kind: str = "md_report"  # md_report | ppt_outline | section


class TemplatePreviewResponse(BaseModel):
    rendered: str
    is_json: bool = False
    error: str | None = None


@router.post("/preview", response_model=TemplatePreviewResponse)
async def preview_template(payload: TemplatePreviewRequest):
    """Render a template against built-in mock data so users can see the result
    while editing. No DB access; pure jinja2."""
    ctx = _mock_ctx()
    try:
        if payload.kind == "ppt_outline":
            obj = render_ppt_outline(payload.prompt_template, ctx)
            return TemplatePreviewResponse(
                rendered=json.dumps(obj, ensure_ascii=False, indent=2),
                is_json=True,
            )
        return TemplatePreviewResponse(
            rendered=render_markdown(payload.prompt_template, ctx),
        )
    except Exception as e:  # noqa: BLE001
        return TemplatePreviewResponse(rendered="", error=str(e)[:500])


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
