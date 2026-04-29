"""ExpertDiscoverer — bidirectional expert mining from snippet clusters.

(1) topic → events/forums → attendee experts (the long-tail miners like 刘烈宏/胡延平/欧阳剑)
(2) topic → known luminaries
(3) cross-provider nomination scoring
"""

from __future__ import annotations

import logging

from app.agents.state import ReportState
from app.db.session import SessionLocal
from app.providers.registry import build_providers
from app.schemas.llm import ExpertDiscoveryOutput

log = logging.getLogger(__name__)

_PROMPT = """你是行业资深编辑，请从下方多源检索片段中识别 **针对所给主题** 有发言权 / 影响力的专家。

要求：
1. 同时挖出 **知名大咖**（如黄仁勋、Pichai、Sam Altman 等）和 **长尾但有影响力**
   的专业人士（例如政策官员、行业研究院院长、企业 CEO/CTO、知名学者、媒体专家）。
   长尾人物示例：刘烈宏（国家数据局局长）、胡延平（上海财大特聘教授）、欧阳剑（昆仑芯 CEO）。
2. 关注从 **事件 / 论坛 / 采访栏目** 反向挖人，比如
   「中国发展高层论坛」「央广财经」「GTC」「Stanford HAI」「a16z Podcast」 出席/受访名单。
3. 输出 ExpertDiscoveryOutput：candidates[] 每人含 name / role / affiliations /
   rationale（为何对此主题有发言权）/ profile_urls / nominated_by_providers /
   relevance_score (0-1)。
4. discovered_events[] 列出片段中识别出的论坛 / 节目 / 报告名（已是新anchor 候选）。

主题：{topics}

可用片段（示例）：
{snippets_excerpt}
"""


async def expert_discoverer_node(state: ReportState) -> dict:
    clusters = state.get("snippets_clusters") or []
    if not clusters:
        return {"expert_candidates": [], "discovered_event_names": []}

    excerpt_lines = []
    for c in clusters[:80]:
        s0 = c["snippets"][0]
        url = c.get("key_url") or ""
        title = c.get("title") or ""
        excerpt_lines.append(
            f"- [{','.join(c['providers'])}] {title} {url}\n  {s0.snippet[:300]}"
        )
    excerpt = "\n".join(excerpt_lines) or "(no snippets)"

    async with SessionLocal() as session:
        providers = await build_providers(session)
    pref = ["anthropic", "openai", "gemini"]
    chosen = next((providers[p] for p in pref if p in providers), None)
    if chosen is None and providers:
        chosen = next(iter(providers.values()))
    if chosen is None:
        return {
            "expert_candidates": [],
            "discovered_event_names": [],
            "errors": ["expert_discoverer: no provider available"],
        }

    prompt = _PROMPT.format(
        topics=", ".join(state.get("focus_topics", [])),
        snippets_excerpt=excerpt,
    )
    try:
        result = await chosen.structured_extract(prompt, ExpertDiscoveryOutput)
    except Exception as e:  # noqa: BLE001
        log.exception("expert discovery extract failed")
        return {
            "expert_candidates": [],
            "discovered_event_names": [],
            "errors": [f"expert_discoverer failed: {e}"],
        }

    out: ExpertDiscoveryOutput = result.data  # type: ignore[assignment]
    return {
        "expert_candidates": out.candidates,
        "discovered_event_names": out.discovered_events,
        "provider_traces": [result.trace],
        "total_cost_usd": result.trace.cost_usd,
        "total_tokens": result.trace.tokens_input + result.trace.tokens_output,
        "notes": [
            f"expert_discoverer: {len(out.candidates)} candidates, "
            f"{len(out.discovered_events)} new events"
        ],
    }
