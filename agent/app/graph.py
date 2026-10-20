from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from app.demo import DemoReasoner
from app.nodes.confirm import confirm_requirements, route_after_confirm
from app.nodes.design import make_design_agent
from app.nodes.locate import make_locate_agent
from app.nodes.publish import make_publish
from app.nodes.report import make_report
from app.nodes.requirement import make_requirement_agent, route_after_requirement
from app.nodes.review import review, route_after_review
from app.nodes.test import make_test_agent
from app.nodes.verify import make_verify, route_after_verify
from app.state import RippleState

LLM_NODES = {"requirement_agent", "locate_agent", "test_agent", "design_agent"}
NODE_TOOLS = {
    "requirement_agent": ("diff_versions",),
    "locate_agent": (
        "search_code",
        "get_file",
        "find_usages",
        "get_db_schema",
        "get_products",
        "get_product_rules",
        "search_regulation",
        "read_resource",
    ),
    "test_agent": ("get_file", "get_db_schema", "get_product_rules"),
    "design_agent": ("get_file",),
    "verify": ("check_patch",),
    "publish": ("create_draft_pr", "create_work_ticket"),
}
SERDE = JsonPlusSerializer(
    allowed_msgpack_modules=[
        ("app.schemas", name)
        for name in (
            "Requirement",
            "TestCase",
            "ChangeSpec",
            "PatchResult",
            "Approval",
            "Delivery",
            "ChangeSheet",
            "Report",
            "Event",
        )
    ]
)


def build_graph(tools, reasoner=None, checkpointer=None):
    if reasoner is None and not tools.is_mock:
        raise ValueError("실제 도구에는 LLM Reasoner를 명시적으로 전달하세요")
    reasoner = reasoner or DemoReasoner()

    def belt(node):
        return tools.subset(*NODE_TOOLS[node])

    graph = StateGraph(RippleState)
    graph.add_node(
        "requirement_agent", make_requirement_agent(belt("requirement_agent"), reasoner)
    )
    graph.add_node("locate_agent", make_locate_agent(belt("locate_agent"), reasoner))
    graph.add_node("confirm_requirements", confirm_requirements)
    graph.add_node("test_agent", make_test_agent(belt("test_agent"), reasoner))
    graph.add_node("design_agent", make_design_agent(belt("design_agent"), reasoner))
    graph.add_node("verify", make_verify(belt("verify")))
    graph.add_node("review", review)
    graph.add_node("publish", make_publish(belt("publish")))
    graph.add_node("report", make_report())
    graph.add_edge(START, "requirement_agent")
    graph.add_conditional_edges(
        "requirement_agent", route_after_requirement, ["locate_agent", "report"]
    )
    graph.add_edge("locate_agent", "confirm_requirements")
    graph.add_conditional_edges(
        "confirm_requirements", route_after_confirm, ["test_agent", "report"]
    )
    graph.add_edge("test_agent", "design_agent")
    graph.add_edge("design_agent", "verify")
    graph.add_conditional_edges(
        "verify", route_after_verify, ["design_agent", "review"]
    )
    graph.add_conditional_edges(
        "review", route_after_review, ["design_agent", "publish", "report"]
    )
    graph.add_edge("publish", "report")
    graph.add_edge("report", END)
    return graph.compile(
        checkpointer=checkpointer
        if checkpointer is not None
        else InMemorySaver(serde=SERDE)
    )
