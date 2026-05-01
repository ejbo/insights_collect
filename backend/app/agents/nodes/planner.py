"""Planner — decompose focus topics into provider/lang-aware sub-queries."""

import logging

from app.agents.main_model import pick_main_model
from app.agents.state import ReportState
from app.db.session import SessionLocal
from app.providers.registry import build_providers
from app.schemas.llm import PlannerOutput, SubQuery

log = logging.getLogger(__name__)

_PROMPT = """你是研究主管。将下列焦点主题分解为 4-8 条具体子查询，
让多家搜索引擎并行检索，最大化召回不同角度的专家观点。

要求：
- 同一主题请同时给出中文 + 英文版本子查询；
- angle 字段填写视角（例如：'权威专家观点' / '行业领袖发言' / '反对声音' /
  '数据与统计' / '事件回顾'）；
- 如果主题与中文圈密切相关（如政策、央媒、国内论坛），lang=zh；其他 lang=en；
  跨地域可用 mixed；
- target_providers 留空表示由系统决定；
- suggested_anchor_events 列出可能挖到该主题专家的论坛/采访栏目（如
  「中国发展高层论坛」「GTC」「Stanford HAI」「a16z Podcast」「央广财经」等）。

焦点主题：{topics}
时间窗：{start} 至 {end}
"""


async def planner_node(state: ReportState) -> dict:
    topics = state.get("focus_topics") or []
    if not topics:
        return {"errors": ["planner: no focus_topics"]}

    async with SessionLocal() as session:
        providers = await build_providers(session)

    chosen, main_model_id = pick_main_model(providers, state)
    if chosen is None:
        # No provider available — produce a trivial fallback plan.
        sub_queries = [
            SubQuery(text=f"{t} 近期专家观点", lang="zh", angle="专家观点")
            for t in topics
        ] + [
            SubQuery(text=f"{t} expert viewpoints recent", lang="en", angle="expert opinions")
            for t in topics
        ]
        plan = PlannerOutput(
            topic_breakdown=topics,
            sub_queries=sub_queries,
            suggested_anchor_events=[],
        )
        return {
            "plan": plan,
            "sub_queries": sub_queries,
            "errors": ["planner: no provider available, fell back to template plan"],
        }

    prompt = _PROMPT.format(
        topics=", ".join(topics),
        start=state["time_range_start"].date(),
        end=state["time_range_end"].date(),
    )
    try:
        result = await chosen.structured_extract(prompt, PlannerOutput, model=main_model_id)
    except Exception as e:  # noqa: BLE001
        log.exception("planner extract failed")
        sub_queries = [SubQuery(text=t, lang="zh", angle="专家观点") for t in topics]
        return {
            "plan": PlannerOutput(topic_breakdown=topics, sub_queries=sub_queries,
                                  suggested_anchor_events=[]),
            "sub_queries": sub_queries,
            "errors": [f"planner failed: {e}"],
        }

    plan: PlannerOutput = result.data  # type: ignore[assignment]
    return {
        "plan": plan,
        "sub_queries": plan.sub_queries,
        "provider_traces": [result.trace],
        "total_cost_usd": result.trace.cost_usd,
        "total_tokens": result.trace.tokens_input + result.trace.tokens_output,
    }
