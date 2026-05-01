"""ReportComposer — produce final analysis bundle, render via templates, write outputs to disk."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from app.agents.main_model import pick_main_model
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


_PROMPT = """你是资深行业分析师。基于下方真实抽取的专家观点 + 聚类，
为这份报告生成 **综合分析包 (FinalAnalysis)**。要求：

- executive_summary: 中文 250-400 字执行摘要。需点名具体专家与他们的核心立场，
  让读者看完就掌握时间窗内争论焦点 + 关键变量。**严禁使用** "近期" / "众多专家"
  这种模糊措辞 — 凡涉及人物，必须给出名字和身份；凡涉及观点，必须给出方向。
- executive_summary_bullets: 5-8 条要点，每条不少于 25 字，必须包含至少一个
  具体的人/机构/数字/事件。
- consensus: 3-6 条共识结论。每条 1-2 句，必须列出 2 名以上代表性专家姓名作为佐证。
- dissent: 3-6 条主要分歧。每条须以「A 认为 X，但 B 反驳 Y」形式呈现，点名两方代表。
- spotlight: 3-6 条值得重点关注的信号 — 长尾权威 / 政策动向 / 数据节点 /
  少数派警告。每条 1-2 句，附人名与场合。
- insight: 3-6 条作者级解读 — 跨观点综合得出的二阶推论或对未来 3-6 月的判断。
  每条须超出原文复述，给出"因此..."的逻辑。

# 写作纪律
- 仅基于提供的观点撰写，不要编造未在输入中出现的人名或事件。
- 引用观点时，请优先用具体引语 (claim_quote) 而非抽象转述。
- 如果某主题输入信息单薄，宁可减少该主题的产出条目，也不要灌水。
- 中英姓名混排时，第一次出现给中文 + 括号英文（如「黄仁勋 (Jensen Huang)」）。

主题：{topics}

小节小结：
{section_summaries}

聚类（按主题，用于结构感知）：
{clusters}

# 候选观点池（请从中挑选论据 — 已按相关性 + 置信度排序）
{viewpoints_excerpt}
"""


def _viewpoints_excerpt_for_prompt(state: ReportState, max_items: int = 60) -> str:
    """Render up to `max_items` viewpoints as compact Markdown bullets the LLM
    can directly cite. Sort by confidence desc, then by claim_when desc."""
    raw = state.get("extracted_viewpoints") or []
    if not raw:
        return "(无)"

    def _sort_key(v):
        conf = getattr(v, "confidence", 0.0) or 0.0
        when = getattr(v, "claim_when", None)
        ts = when.timestamp() if when else 0.0
        return (-conf, -ts)

    items = sorted(raw, key=_sort_key)[:max_items]
    lines = []
    for i, v in enumerate(items, 1):
        when = v.claim_when.date().isoformat() if getattr(v, "claim_when", None) else "时间未知"
        role = (getattr(v, "expert_role", None) or "").strip()
        venue = (getattr(v, "claim_medium", None) or getattr(v, "claim_where", None) or "").strip()
        url = (getattr(v, "claim_source_url", None) or "").strip()
        quote = (getattr(v, "claim_quote", None) or getattr(v, "claim_what", "") or "").replace("\n", " ").strip()
        if len(quote) > 280:
            quote = quote[:280] + "…"
        lines.append(
            f"{i}. **{v.expert_name}**"
            + (f" ({role})" if role else "")
            + f" · {when}"
            + (f" · {venue}" if venue else "")
            + f"\n   > {quote}"
            + (f"\n   <{url}>" if url else "")
        )
    return "\n".join(lines)


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
    chosen, main_model_id = pick_main_model(providers, state)

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
            viewpoints_excerpt=_viewpoints_excerpt_for_prompt(state),
        )
        try:
            comp_res = await chosen.structured_extract(
                prompt, ReportCompositionOutput, model=main_model_id,
            )
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
                section_summaries=[
                    {"topic": t, "summary": s}  # type: ignore[list-item]
                    for t, s in (state.get("section_summaries") or {}).items()
                ],
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
            section_summaries=[
                {"topic": t, "summary": s}  # type: ignore[list-item]
                for t, s in (state.get("section_summaries") or {}).items()
            ],
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
