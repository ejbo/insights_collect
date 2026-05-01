"""ExpertDiscoverer — bidirectional expert mining from snippet clusters.

(1) topic → events/forums → attendee experts (the long-tail miners like 刘烈宏/胡延平/欧阳剑)
(2) topic → known luminaries
(3) cross-provider nomination scoring
"""

from __future__ import annotations

import logging

from app.agents.main_model import pick_main_model
from app.agents.state import ReportState
from app.db.session import SessionLocal
from app.providers.registry import build_providers
from app.schemas.llm import ExpertDiscoveryOutput

log = logging.getLogger(__name__)

_PROMPT = """你是行业资深编辑。基于下方多源检索片段，做一次 **深度的双向专家挖掘**。

# 双向挖掘的两条路径
A. **由人到事**：对每位浮现的专家，确认他/她在主题相关时间窗内 **具体说过什么 / 在哪里说**。
B. **由事到人**：对片段里出现过的论坛、采访栏目、报告、Podcast、博客系列、专栏、研究机构，
   反向找出 **演讲者 / 受访人 / 联合作者 / 主理人** 名单。常见 anchor：
   - 中国：中国发展高层论坛、世界互联网大会、央广财经、第一财经《问道》、清华五道口、
     上海财大、CFTL、信通院、国家数据局、CGTN、36 氪、虎嗅、晚点 LatePost、
     《财新周刊》、《中国企业家》、张志东《Sirius Times》。
   - 全球：GTC、Stanford HAI、MIT CSAIL、a16z Podcast、Acquired、Lex Fridman、
     Stratechery、Ben's Bites、Latent Space、All-In、20VC、Pivot、Bloomberg
     Originals、The Information、Forbes、Y Combinator Talks、World Economic Forum。

# 候选画像要求
为每位 candidate 给出：
- name（必须，原文最常见拼写） + name_zh（中文名，如不同于 name）
- role（最现职务，如「Co-founder & CEO @ Lightspark」）
- affiliations（一并列出过去重要任职 / 现任，如 ["Lightspark CEO", "Ex-PayPal President"]）
- profile_urls（X / LinkedIn / 专栏页 / 公司主页 / 学术主页 — 至少 1 条）
- rationale（**1-3 句**说明：他/她为何对该主题有发言权，最好引用最具代表性的近期片段
  或观点签名 phrase）
- nominated_by_providers（这位专家在哪些 provider 的检索结果里被提到 — 用片段头的
  `[anthropic,gemini,...]` 标记反推；交叉证据越多越可信）
- relevance_score (0-1)：综合 (a) 在该主题的发声密度 (b) 跨源被提及次数 (c) 影响力层级
  (d) 信息新鲜度 给一个加权分数。
- 同时挖 **知名大咖** 与 **长尾权威**（政策官员、研究院院长、CTO、专栏作者、独立分析师）。
  长尾示例：刘烈宏（国家数据局局长）、胡延平（上海财大特聘教授）、欧阳剑（昆仑芯 CEO）、
  Packy McCormick（Not Boring）、Eugene Yan、Simon Willison。

# Discovered events 要求
discovered_events[] 列出 **可作为 anchor 复用** 的论坛 / 节目 / 报告名 / 专栏，
帮助下一轮检索从「人 → 事 → 更多人」继续滚动。

# 严禁
- 不要凭空臆造名字；只在下方片段或 anchor 类型里能立得住才输出。
- 同一专家不要重复，相似别名（中英、缩写）合并到 affiliations 里。
- 至少给 8 位候选；目标 12–25 位；如片段确实稀疏才低于此区间。

主题：{topics}

可用片段：
{snippets_excerpt}
"""


async def expert_discoverer_node(state: ReportState) -> dict:
    clusters = state.get("snippets_clusters") or []
    if not clusters:
        return {"expert_candidates": [], "discovered_event_names": []}

    # Use up to 200 clusters and keep each excerpt longer — deeper context lets
    # the model spot long-tail experts (官员/专栏作者/CTO) it would otherwise miss.
    excerpt_lines = []
    for c in clusters[:200]:
        s0 = c["snippets"][0]
        url = c.get("key_url") or ""
        title = c.get("title") or ""
        domain = c.get("domain") or ""
        excerpt_lines.append(
            f"- [{','.join(c['providers'])}] {title} ({domain}) {url}\n  {s0.snippet[:500]}"
        )
    excerpt = "\n".join(excerpt_lines) or "(no snippets)"

    async with SessionLocal() as session:
        providers = await build_providers(session)
    chosen, main_model_id = pick_main_model(providers, state)
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
        result = await chosen.structured_extract(prompt, ExpertDiscoveryOutput, model=main_model_id)
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
