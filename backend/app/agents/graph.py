"""LangGraph wiring — main report-generation graph.

Linear pipeline:
  Planner → MultiSearch → DedupMerger → ExpertDiscoverer → ViewpointExtractor
       → ClusterAnalyzer → KnowledgeWriter → EventCurator → ReportComposer

Critic ↔ GapFiller reflection cycle is staged for v2; the schema (ReportState fields,
provider_traces accumulator) already supports it without re-architecting.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.agents.nodes.cluster_analyzer import cluster_analyzer_node
from app.agents.nodes.dedup_merger import dedup_merger_node
from app.agents.nodes.event_curator import event_curator_node
from app.agents.nodes.expert_discoverer import expert_discoverer_node
from app.agents.nodes.knowledge_writer import knowledge_writer_node
from app.agents.nodes.multi_search import multi_search_node
from app.agents.nodes.planner import planner_node
from app.agents.nodes.report_composer import report_composer_node
from app.agents.nodes.viewpoint_extractor import viewpoint_extractor_node
from app.agents.state import ReportState


def build_report_graph():
    g = StateGraph(ReportState)

    g.add_node("planner", planner_node)
    g.add_node("multi_search", multi_search_node)
    g.add_node("dedup_merger", dedup_merger_node)
    g.add_node("expert_discoverer", expert_discoverer_node)
    g.add_node("viewpoint_extractor", viewpoint_extractor_node)
    g.add_node("cluster_analyzer", cluster_analyzer_node)
    g.add_node("knowledge_writer", knowledge_writer_node)
    g.add_node("event_curator", event_curator_node)
    g.add_node("report_composer", report_composer_node)

    g.add_edge(START, "planner")
    g.add_edge("planner", "multi_search")
    g.add_edge("multi_search", "dedup_merger")
    g.add_edge("dedup_merger", "expert_discoverer")
    g.add_edge("expert_discoverer", "viewpoint_extractor")
    g.add_edge("viewpoint_extractor", "cluster_analyzer")
    g.add_edge("cluster_analyzer", "knowledge_writer")
    g.add_edge("knowledge_writer", "event_curator")
    g.add_edge("event_curator", "report_composer")
    g.add_edge("report_composer", END)

    return g.compile()


# Singleton compiled graph (no checkpointer — added in runner per-thread).
report_graph = build_report_graph()
