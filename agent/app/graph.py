from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph

from app.nodes.confirm import confirm_requirements, route_after_confirm
from app.nodes.design import make_plan, make_worker, merge, route_after_merge, route_after_plan
from app.nodes.locate import make_locate_agent
from app.nodes.publish import make_publish
from app.nodes.report import make_report
from app.nodes.requirement import make_requirement_agent, route_after_requirement
from app.nodes.review import review, route_after_review
from app.nodes.test import make_test_agent
from app.nodes.verify import make_verify, route_after_verify
from app.state import RippleState

# 노드별 최소 권한. 쓰기 도구는 코드 노드 publish에만.
LLM_NODES = {"requirement_agent", "test_agent", "locate_agent", "plan", "worker"}
NODE_TOOLS: dict[str, tuple[str, ...]] = {
    "requirement_agent": ("diff_versions", "search_regulation"),
    "test_agent": ("get_file", "get_db_schema", "get_product_rules"),
    "locate_agent": ("search_code", "get_file", "find_usages", "get_db_schema", "get_product_rules", "search_regulation"),
    "plan": ("get_file", "find_usages", "get_db_schema"),
    "worker": ("get_file", "find_usages"),
    "verify": ("check_patch",),
    "publish": ("create_draft_pr", "create_work_ticket"),
    "report": ("read_resource",),
}

# 체크포인트에서 복원을 허용할 타입 (PostgresSaver로 바꿀 때도 같은 serde를 넘긴다)
SERDE = JsonPlusSerializer(
    allowed_msgpack_modules=[
        ("app.schemas", name)
        for name in ("Requirement", "TestCase", "ChangeSpec", "PlanItem", "Contract", "Bundle", "Plan",
                     "PatchResult", "Approval", "Delivery", "ChangeSheet", "Report", "Event")
    ]
)


def build_graph(tools, checkpointer=None):
    def t(node: str):
        return tools.subset(*NODE_TOOLS[node])

    g = StateGraph(RippleState)
    g.add_node("requirement_agent", make_requirement_agent(t("requirement_agent")))
    g.add_node("confirm_requirements", confirm_requirements)
    g.add_node("test_agent", make_test_agent(t("test_agent")))
    g.add_node("locate_agent", make_locate_agent(t("locate_agent")))
    g.add_node("plan", make_plan(t("plan")))
    g.add_node("worker", make_worker(t("worker")))
    g.add_node("merge", merge)
    g.add_node("verify", make_verify(t("verify")))
    g.add_node("review", review)
    g.add_node("publish", make_publish(t("publish")))
    g.add_node("report", make_report(t("report")))

    g.add_edge(START, "requirement_agent")
    g.add_conditional_edges("requirement_agent", route_after_requirement, ["confirm_requirements", "report"])
    g.add_conditional_edges("confirm_requirements", route_after_confirm, ["test_agent", "locate_agent", "report"])
    # test_agent는 한 번만 돌고 끝난다. verify는 merge에서만 트리거, 테스트는 state에서 읽는다.
    g.add_edge("test_agent", END)
    g.add_edge("locate_agent", "plan")
    g.add_conditional_edges("plan", route_after_plan, ["worker", "merge"])
    g.add_edge("worker", "merge")
    g.add_conditional_edges("merge", route_after_merge, ["worker", "verify"])
    g.add_conditional_edges("verify", route_after_verify, ["locate_agent", "plan", "review"])
    g.add_conditional_edges("review", route_after_review, ["verify", "publish", "report"])
    g.add_edge("publish", "report")
    g.add_edge("report", END)

    return g.compile(checkpointer=checkpointer or InMemorySaver(serde=SERDE))
