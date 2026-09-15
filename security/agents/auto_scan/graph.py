# ============================================================
# security/agents/auto_scan/graph.py — LangGraph 状态图 (pentest 移植)
# ============================================================

from __future__ import annotations

from langgraph.graph import END, StateGraph

from security.agents.auto_scan.nodes import (
    recon_node,
    fingerprint_node,
    scan_node,
    analyze_node,
    report_node,
)
from security.agents.auto_scan.state import ScanState


def build_auto_scan_graph():
    workflow = StateGraph(ScanState)

    workflow.add_node("recon", recon_node)
    workflow.add_node("fingerprint", fingerprint_node)
    workflow.add_node("scan", scan_node)
    workflow.add_node("analyze", analyze_node)
    workflow.add_node("report", report_node)

    workflow.set_entry_point("recon")

    workflow.add_edge("recon", "fingerprint")
    workflow.add_edge("fingerprint", "scan")
    workflow.add_edge("scan", "analyze")
    workflow.add_edge("analyze", "report")
    workflow.add_edge("report", END)

    return workflow.compile()


# 惰性构建，避免导入时对 langgraph 的强依赖
auto_scan_graph = None


def get_auto_scan_graph():
    global auto_scan_graph
    if auto_scan_graph is None:
        auto_scan_graph = build_auto_scan_graph()
    return auto_scan_graph
