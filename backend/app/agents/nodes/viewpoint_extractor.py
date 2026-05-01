"""ViewpointExtractor — produce 7-tuple viewpoints from snippets keyed by candidate experts."""

from __future__ import annotations

import logging

from app.agents.main_model import pick_main_model
from app.agents.state import ReportState
from app.db.session import SessionLocal
from app.providers.registry import build_providers
from app.schemas.llm import ViewpointExtractionOutput

log = logging.getLogger(__name__)

_PROMPT = """从下方多源片段中抽取 **结构化专家观点**（7 元组）。

为下列每位候选专家寻找其在主题相关时间窗内的公开发言/写作。每条观点必须含：
- expert_name (Who) + expert_role
- claim_when (When)
- claim_where (Where: 论坛、地点、节目)
- claim_what (What: 观点摘要) + claim_quote (原话引用，若可得)
- claim_medium (论坛 / 采访栏目 / 文章 / 推文 等)
- claim_source_url (Source，必填，没有就不要捏造)
- claim_why_context (Why: 为何此时此地说这话)
- claim_lang
- confidence (0-1)

要求：
- 不要凭空捏造引用；缺信息的字段保持 null。
- claim_source_url 必须出自下方片段；找不到原文链接的观点不要输出。
- 同一专家在同一事件多条小观点可拆分多条。

主题：{topics}
候选专家：
{candidates}

可用片段：
{snippets}
"""


def _candidate_lines(candidates: list) -> str:
    if not candidates:
        return "(无 — 让模型自行从片段中识别专家)"
    return "\n".join(
        f"- {c.name} ({c.role or '?'}) :: {c.rationale}" for c in candidates[:40]
    )


async def viewpoint_extractor_node(state: ReportState) -> dict:
    clusters = state.get("snippets_clusters") or []
    if not clusters:
        return {"extracted_viewpoints": []}

    snippet_text_chunks: list[str] = []
    for c in clusters[:80]:
        s0 = c["snippets"][0]
        url = c.get("key_url") or ""
        title = c.get("title") or ""
        snippet_text_chunks.append(
            f"## {title}\nURL: {url}\nProviders: {','.join(c['providers'])}\n\n"
            f"{s0.snippet[:1200]}"
        )
    snippets_block = "\n---\n".join(snippet_text_chunks) or "(empty)"

    async with SessionLocal() as session:
        providers = await build_providers(session)
    chosen, main_model_id = pick_main_model(providers, state)
    if chosen is None:
        return {
            "extracted_viewpoints": [],
            "errors": ["viewpoint_extractor: no provider available"],
        }

    prompt = _PROMPT.format(
        topics=", ".join(state.get("focus_topics", [])),
        candidates=_candidate_lines(state.get("expert_candidates") or []),
        snippets=snippets_block,
    )
    try:
        result = await chosen.structured_extract(prompt, ViewpointExtractionOutput, model=main_model_id)
    except Exception as e:  # noqa: BLE001
        log.exception("viewpoint extraction failed")
        return {
            "extracted_viewpoints": [],
            "errors": [f"viewpoint_extractor failed: {e}"],
        }

    out: ViewpointExtractionOutput = result.data  # type: ignore[assignment]
    return {
        "extracted_viewpoints": out.viewpoints,
        "provider_traces": [result.trace],
        "total_cost_usd": result.trace.cost_usd,
        "total_tokens": result.trace.tokens_input + result.trace.tokens_output,
        "notes": [f"viewpoint_extractor: {len(out.viewpoints)} viewpoints"],
    }
