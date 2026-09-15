# ============================================================
# security/agents/guided/graph.py — LangGraph 引导模式状态图 (pentest 移植)
# ============================================================

from __future__ import annotations

from langgraph.graph import END, StateGraph

from security.agents.guided.nodes import init_node, process_result_node, report_node
from security.agents.guided.state import GuidedState


def build_guided_graph():
    workflow = StateGraph(GuidedState)

    workflow.add_node("init", init_node)
    workflow.add_node("process_result", process_result_node)
    workflow.add_node("report", report_node)

    workflow.set_entry_point("init")
    workflow.add_edge("init", "process_result")

    def should_continue(state: GuidedState) -> str:
        if state["current_stage"] == "summary":
            return "report"
        return "process_result"

    workflow.add_conditional_edges(
        "process_result",
        should_continue,
        {"process_result": "process_result", "report": "report"},
    )

    workflow.add_edge("report", END)

    return workflow.compile()


guided_graph = None


def get_guided_graph():
    global guided_graph
    if guided_graph is None:
        guided_graph = build_guided_graph()
    return guided_graph
