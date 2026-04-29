"""ReportComposer — produce final analysis bundle, render via templates, write outputs to disk."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from app.agents.state import ReportState
from app.config import get_settings
from app.db import models
from app.db.session import SessionLocal
from app.providers.registry import build_providers
from app.render.markdown_renderer import render_markdown
from app.render.pdf_renderer import render_pdf
from app.render.ppt_outline_renderer import render_ppt_outline
from app.schemas.llm import ReportCompositionOutput

log = logging.getLogger(__name__)


_PROMPT = """请基于已聚类的专家观点，为这份报告生成 **综合分析包 (FinalAnalysis)**：

- executive_summary: 一段 200 字内的中文执行摘要
- executive_summary_bullets: 3-5 条要点
- consensus / dissent / spotlight / insight: 各列出 3-6 条主要发现
- section_summaries: 每个主题的小结（已在输入提供，可润色保留）

主题：{topics}
小节小结：
{section_summaries}

聚类（按主题）：
{clusters}
"""


def _slugify(s: str) -> str:
    s = re.sub(r"\s+", "-", s.strip())
    s = re.sub(r"[^A-Za-z0-9_\-一-鿿]", "", s)
    return s[:50] or "report"


async def _load_template(template_id: int | None, kind_fallback: str) -> models.ReportTemplate | None:
    async with SessionLocal() as session:
        if template_id is not None:
            row = (await session.execute(
                select(models.ReportTemplate).where(models.ReportTemplate.id == template_id)
            )).scalar_one_or_none()
            if row is not None:
                return row
        # fallback: first default of given kind
        row = (await session.execute(
            select(models.ReportTemplate)
            .where(models.ReportTemplate.kind == kind_fallback,
                   models.ReportTemplate.is_default.is_(True))
        )).scalar_one_or_none()
        if row is not None:
            return row
        # last resort: first builtin of kind
        row = (await session.execute(
            select(models.ReportTemplate).where(
                models.ReportTemplate.kind == kind_fallback,
                models.ReportTemplate.is_builtin.is_(True),
            )
        )).scalar_one_or_none()
        return row


def _viewpoints_for_render(state: ReportState) -> list[dict]:
    """Convert ExtractedViewpoint objects to render-friendly dicts (so Jinja can `{{ v.field }}`)."""
    out = []
    for v in state.get("extracted_viewpoints") or []:
        out.append({
            "expert_name": v.expert_name,
            "claim_who_role": v.expert_role,
            "claim_when": v.claim_when,
            "claim_where": v.claim_where,
            "claim_what": v.claim_what,
            "claim_quote": v.claim_quote,
            "claim_medium": v.claim_medium,
            "claim_source_url": v.claim_source_url,
            "claim_why_context": v.claim_why_context,
            "source_domain": _domain_from(v.claim_source_url),
        })
    return out


def _domain_from(url: str | None) -> str | None:
    if not url:
        return None
    try:
        from urllib.parse import urlparse
        return (urlparse(url).hostname or "").lower().lstrip("www.")
    except Exception:  # noqa: BLE001
        return None


def _build_sections(state: ReportState, all_viewpoints_render: list[dict]) -> list[dict]:
    """Assemble per-topic sections by mapping cluster.viewpoint_indices back into render-shaped vps."""
    section_summaries = state.get("section_summaries") or {}
    sections = []
    for topic, clusters in (state.get("clusters_by_topic") or {}).items():
        cluster_dicts = []
        for c in clusters:
            cluster_vps = [
                all_viewpoints_render[i]
                for i in (c.viewpoint_indices or [])
                if 0 <= i < len(all_viewpoints_render)
            ]
            cluster_dicts.append({
                "label": c.label,
                "kind": c.kind,
                "summary_md": c.summary_md,
                "viewpoints": cluster_vps,
            })
        sections.append({
            "topic_name": topic,
            "clusters": cluster_dicts,
            "section_summary": section_summaries.get(topic, ""),
        })
    return sections


def _persist_paths(state: ReportState) -> tuple[Path, Path, Path]:
    settings = get_settings()
    rid = state.get("report_id")
    slug = _slugify(state.get("title", "report"))
    stem = f"{rid}-{slug}-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
    md_path = settings.reports_dir / f"{stem}.md"
    out_path = settings.outlines_dir / f"{stem}.json"
    pdf_path = settings.pdfs_dir / f"{stem}.pdf"
    return md_path, out_path, pdf_path


async def report_composer_node(state: ReportState) -> dict:
    # 1) get final analysis
    async with SessionLocal() as session:
        providers = await build_providers(session)
    pref = ["anthropic", "openai", "gemini"]
    chosen = next((providers[p] for p in pref if p in providers), None)
    if chosen is None and providers:
        chosen = next(iter(providers.values()))

    cluster_text = json.dumps(
        {
            t: [{"label": c.label, "kind": c.kind, "summary": c.summary_md[:300]}
                for c in clusters]
            for t, clusters in (state.get("clusters_by_topic") or {}).items()
        },
        ensure_ascii=False,
        indent=2,
    )
    section_summaries_text = json.dumps(state.get("section_summaries") or {}, ensure_ascii=False, indent=2)

    if chosen is not None:
        prompt = _PROMPT.format(
            topics=", ".join(state.get("focus_topics", [])),
            section_summaries=section_summaries_text,
            clusters=cluster_text,
        )
        try:
            comp_res = await chosen.structured_extract(prompt, ReportCompositionOutput)
            comp: ReportCompositionOutput = comp_res.data  # type: ignore[assignment]
            traces = [comp_res.trace]
        except Exception as e:  # noqa: BLE001
            log.exception("composer extract failed: %s", e)
            comp = ReportCompositionOutput(
                title=state.get("title", "report"),
                analysis={  # type: ignore[arg-type]
                    "executive_summary": "（生成失败，已使用占位）",
                    "executive_summary_bullets": [],
                    "consensus": [], "dissent": [], "spotlight": [], "insight": [],
                },
                section_summaries=state.get("section_summaries") or {},
            )
            traces = []
    else:
        comp = ReportCompositionOutput(
            title=state.get("title", "report"),
            analysis={  # type: ignore[arg-type]
                "executive_summary": "（无可用 LLM provider）",
                "executive_summary_bullets": [],
                "consensus": [], "dissent": [], "spotlight": [], "insight": [],
            },
            section_summaries=state.get("section_summaries") or {},
        )
        traces = []

    # 2) load templates
    md_template = await _load_template(state.get("md_template_id"), "md_report")
    outline_template = await _load_template(state.get("outline_template_id"), "ppt_outline")

    # 3) build render context
    all_viewpoints = _viewpoints_for_render(state)
    sections = _build_sections(state, all_viewpoints)
    ctx = {
        "title": state.get("title", "report"),
        "focus_topics": state.get("focus_topics") or [],
        "time_range_start": state["time_range_start"],
        "time_range_end": state["time_range_end"],
        "sections": sections,
        "analysis": comp.analysis,
        "all_viewpoints": all_viewpoints,
        "top_viewpoints": all_viewpoints[:6],
    }

    md_path, outline_path, pdf_path = _persist_paths(state)

    md_text = ""
    if md_template:
        try:
            md_text = render_markdown(md_template.prompt_template, ctx)
            md_path.write_text(md_text, encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            log.exception("markdown render failed")
            return {
                "errors": [f"report_composer markdown render failed: {e}"],
                "final_analysis": comp.analysis,
                "provider_traces": traces,
            }

    outline_obj: dict | None = None
    if outline_template:
        try:
            outline_obj = render_ppt_outline(outline_template.prompt_template, ctx)
            outline_path.write_text(
                json.dumps(outline_obj, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:  # noqa: BLE001
            log.warning("outline render failed: %s", e)

    pdf_ok = False
    if md_text:
        try:
            render_pdf(md_text, pdf_path, title=state.get("title", "report"))
            pdf_ok = True
        except Exception as e:  # noqa: BLE001
            log.warning("pdf render failed: %s", e)

    # 4) persist paths + final analysis on Report row
    rid = state.get("report_id")
    if rid:
        async with SessionLocal() as session:
            row = (await session.execute(
                select(models.Report).where(models.Report.id == rid)
            )).scalar_one_or_none()
            if row is not None:
                row.md_path = str(md_path) if md_text else None
                row.outline_json_path = str(outline_path) if outline_obj else None
                row.pdf_path = str(pdf_path) if pdf_ok else None
                await session.commit()

    return {
        "final_analysis": comp.analysis,
        "md_path": str(md_path) if md_text else None,
        "outline_json_path": str(outline_path) if outline_obj else None,
        "pdf_path": str(pdf_path) if pdf_ok else None,
        "provider_traces": traces,
        "total_cost_usd": sum(t.cost_usd for t in traces),
        "total_tokens": sum(t.tokens_input + t.tokens_output for t in traces),
        "notes": [f"report_composer: md={bool(md_text)} outline={bool(outline_obj)} pdf={pdf_ok}"],
    }
