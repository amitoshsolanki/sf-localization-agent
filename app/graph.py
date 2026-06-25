from typing import Literal

from langgraph.graph import END, StateGraph

from app.nodes.auditor import auditor_node
from app.nodes.extractor import extractor_node
from app.nodes.parser import parser_node
from app.nodes.translator import translator_node
from app.nodes.validator import validator_node
from app.state import AgentState

MAX_RETRIES = 3


def _route_after_validation(state: AgentState) -> Literal["translator", "extractor", "__end__"]:
    if state.get("failed_segment_ids") and state.get("loop_count", 0) < MAX_RETRIES:
        return "translator"
    if state.get("output_stf"):
        return "extractor"
    return "__end__"


def build_graph(checkpointer=None):
    builder = StateGraph(AgentState)

    builder.add_node("parser", parser_node)
    builder.add_node("translator", translator_node)
    builder.add_node("auditor", auditor_node)
    builder.add_node("validator", validator_node)
    builder.add_node("extractor", extractor_node)

    builder.set_entry_point("parser")
    builder.add_edge("parser", "translator")
    builder.add_edge("translator", "auditor")
    builder.add_edge("auditor", "validator")
    builder.add_conditional_edges(
        "validator",
        _route_after_validation,
        {"translator": "translator", "extractor": "extractor", "__end__": END},
    )
    builder.add_edge("extractor", END)

    return builder.compile(checkpointer=checkpointer)
