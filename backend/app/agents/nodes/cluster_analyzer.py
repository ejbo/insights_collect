"""ClusterAnalyzer — group viewpoints per topic and label clusters
(consensus / dissent / spotlight / insight). LLM-driven, not sentiment analysis.
"""

from __future__ import annotations

import logging

from app.agents.state import ReportState
from app.db.session import SessionLocal
from app.providers.registry import build_providers
from app.schemas.llm import ClusterAnalysisOutput

log = logging.getLogger(__name__)

_PROMPT = """对下方专家观点按 **主题分组** 后再做 **深度聚类**：

- 每个主题下产出若干 cluster；每个 cluster 含 label / kind / summary_md / viewpoint_indices
- kind ∈ {{consensus(共识), dissent(分歧), spotlight(重点), insight(启示)}}
- summary_md：用 markdown 写 1-2 段，体现观点之间的 **共同点 / 分歧 / 重点信号 / 启示**，不要做简单情感分析
- viewpoint_indices：所属观点在输入数组中的下标（0-based）

主题列表：{topics}

观点（按下标）：
{viewpoints}
"""


def _viewpoint_lines(viewpoints: list) -> str:
    lines = []
    for i, v in enumerate(viewpoints):
        when = v.claim_when.date() if v.claim_when else "n.d."
        where = v.claim_where or v.claim_medium or ""
        lines.append(
            f"[{i}] {v.expert_name} ({v.expert_role or ''}) · {when} · {where}\n"
            f"    {v.claim_what[:200]}"
        )
    return "\n".join(lines)


async def cluster_analyzer_node(state: ReportState) -> dict:
    viewpoints = state.get("extracted_viewpoints") or []
    if not viewpoints:
        return {
            "clusters_by_topic": {},
            "section_summaries": {},
            "notes": ["cluster_analyzer: no viewpoints to cluster"],
        }

    async with SessionLocal() as session:
        providers = await build_providers(session)
    pref = ["anthropic", "openai", "gemini"]
    chosen = next((providers[p] for p in pref if p in providers), None)
    if chosen is None and providers:
        chosen = next(iter(providers.values()))
    if chosen is None:
        return {
            "clusters_by_topic": {},
            "section_summaries": {},
            "errors": ["cluster_analyzer: no provider available"],
        }

    prompt = _PROMPT.format(
        topics=", ".join(state.get("focus_topics", [])),
        viewpoints=_viewpoint_lines(viewpoints),
    )
    try:
        result = await chosen.structured_extract(prompt, ClusterAnalysisOutput)
    except Exception as e:  # noqa: BLE001
        log.exception("cluster analysis failed")
        return {
            "clusters_by_topic": {},
            "section_summaries": {},
            "errors": [f"cluster_analyzer failed: {e}"],
        }
    out: ClusterAnalysisOutput = result.data  # type: ignore[assignment]

    # Generate per-topic short summary by analyze() call
    section_summaries: dict[str, str] = {}
    for topic, clusters in out.clusters_per_topic.items():
        cluster_lines = [
            f"- ({c.kind}) {c.label}: {c.summary_md[:200]}" for c in clusters
        ]
        try:
            sum_res = await chosen.analyze(
                f"为主题「{topic}」写一段 100 字内的中文小结，"
                f"概括下面 cluster 的整体格局：\n" + "\n".join(cluster_lines)
            )
            section_summaries[topic] = sum_res.text.strip()
        except Exception as e:  # noqa: BLE001
            log.warning("section summary failed for %s: %s", topic, e)
            section_summaries[topic] = ""

    return {
        "clusters_by_topic": out.clusters_per_topic,
        "section_summaries": section_summaries,
        "provider_traces": [result.trace],
        "total_cost_usd": result.trace.cost_usd,
        "total_tokens": result.trace.tokens_input + result.trace.tokens_output,
        "notes": [
            f"cluster_analyzer: {sum(len(v) for v in out.clusters_per_topic.values())} clusters across "
            f"{len(out.clusters_per_topic)} topics"
        ],
    }
