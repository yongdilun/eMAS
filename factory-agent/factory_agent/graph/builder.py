from __future__ import annotations

from langgraph.graph import END, StateGraph

from ..config import Settings
from .errors import LangGraphPlannerError
from .nodes import (
    clarify_end_node,
    decision_guard_node,
    fatal_end_node,
    input_layer_node,
    intent_splitter_node,
    make_bundle_dry_run_node,
    make_commit_node,
    make_final_validator_node,
    make_planner_node,
    make_relevance_filter_node,
    make_tool_execution_node,
    prepare_node,
    route_after_bundle,
    route_after_commit,
    route_after_guard,
    route_after_planner,
    route_after_relevance,
    route_after_tool,
    route_after_validate,
    synthesize_plan_node,
)
from .state import AgentState


def compile_planner_graph(settings: Settings):
    try:
        import langgraph.graph  # noqa: F401 — verify dependency at compile time
    except Exception as exc:
        raise LangGraphPlannerError("langgraph is required for the planner graph.") from exc

    graph = StateGraph(AgentState)
    graph.add_node("input_layer", input_layer_node)
    graph.add_node("intent_splitter", intent_splitter_node)
    graph.add_node("prepare", prepare_node)
    graph.add_node("planner", make_planner_node(settings))
    graph.add_node("decision_guard", decision_guard_node)
    graph.add_node("tool_execution", make_tool_execution_node(settings))
    graph.add_node("relevance_filter", make_relevance_filter_node(settings))
    graph.add_node("synthesize_plan", synthesize_plan_node)
    graph.add_node("final_validator", make_final_validator_node(settings))
    graph.add_node("bundle_dry_run", make_bundle_dry_run_node(settings))
    graph.add_node("commit", make_commit_node(settings))
    graph.add_node("fatal_end", fatal_end_node)
    graph.add_node("clarify_end", clarify_end_node)

    graph.set_entry_point("input_layer")
    graph.add_edge("input_layer", "intent_splitter")
    graph.add_edge("intent_splitter", "prepare")
    graph.add_edge("prepare", "planner")

    graph.add_conditional_edges(
        "planner",
        route_after_planner,
        {
            "clarify_end": "clarify_end",
            "continue_planner": "planner",
            "decision_guard": "decision_guard",
            "synthesize_plan": "synthesize_plan",
        },
    )
    graph.add_conditional_edges(
        "decision_guard",
        route_after_guard,
        {
            "continue_planner": "planner",
            "tool_execution": "tool_execution",
        },
    )
    graph.add_conditional_edges(
        "tool_execution",
        route_after_tool,
        {
            "fatal_end": "fatal_end",
            "relevance_filter": "relevance_filter",
        },
    )
    graph.add_conditional_edges(
        "relevance_filter",
        route_after_relevance,
        {
            "fatal_end": "fatal_end",
            "continue_planner": "planner",
            "synthesize_plan": "synthesize_plan",
        },
    )
    graph.add_edge("synthesize_plan", "final_validator")
    graph.add_conditional_edges(
        "final_validator",
        route_after_validate,
        {
            "continue_planner": "planner",
            "fatal_end": "fatal_end",
            "bundle_dry_run": "bundle_dry_run",
            "commit": "commit",
            "end": END,
        },
    )
    graph.add_conditional_edges(
        "bundle_dry_run",
        route_after_bundle,
        {
            "fatal_end": "fatal_end",
            "final_validator": "final_validator",
        },
    )
    graph.add_conditional_edges(
        "commit",
        route_after_commit,
        {
            "fatal_end": "fatal_end",
            "final_validator": "final_validator",
            "end": END,
        },
    )
    graph.add_edge("fatal_end", END)
    graph.add_edge("clarify_end", END)
    from .checkpointing import build_graph_checkpointer, get_process_memory_checkpointer

    checkpointer = build_graph_checkpointer(settings)
    if checkpointer is None:
        backend = (settings.graph_checkpoint_backend or "auto").strip().lower() or "auto"
        if backend == "off":
            return graph.compile()
        try:
            checkpointer = get_process_memory_checkpointer()
        except Exception as exc:
            raise LangGraphPlannerError(
                "LangGraph checkpointer is required for planner approvals (interrupt/resume). "
                "Set GRAPH_CHECKPOINT_BACKEND=memory|auto|db, or ensure langgraph.checkpoint.memory is available."
            ) from exc
    return graph.compile(checkpointer=checkpointer)
