"""법령 → 상품 영향 → 변경 제안 → 항목별 검토. 중간 승인·코드 실행은 없다."""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from app.nodes.requirement import make_requirement_agent, route_after_requirement
from app.nodes.impact import make_product_impact_agent, route_after_impact
from app.nodes.proposal import make_proposal_agent
from app.nodes.verify import make_verify, route_after_verify
from app.nodes.review import review, route_after_review
from app.nodes.report import make_report
from app.nodes.apply import make_apply
from app.state import RippleState

LLM_NODES = {"requirement_agent", "product_impact_agent", "proposal_agent"}
NODE_TOOLS = {"requirement_agent": ("diff_versions", "get_regulation_context"),
              "product_impact_agent": ("get_products", "get_product_rules", "get_product_documents")}
SERDE = JsonPlusSerializer(allowed_msgpack_modules=[("app.schemas", name) for name in (
    "Requirement", "RuleChange", "ScopeCondition", "ProductImpact", "ProductProposal", "ProposalReviewRecord", "ProductReport", "Event", "ApplyApproval", "ApplyResult")])


def build_graph(tools, reasoner, checkpointer=None, *, job_reader=None, apply_timeout=60, poll_interval=1):
    if reasoner is None:
        raise ValueError("LLM Reasoner가 필요합니다")
    graph = StateGraph(RippleState)
    graph.add_node("requirement_agent", make_requirement_agent(tools.subset(*NODE_TOOLS["requirement_agent"]), reasoner))
    graph.add_node("product_impact_agent", make_product_impact_agent(tools.subset(*NODE_TOOLS["product_impact_agent"]), reasoner))
    graph.add_node("proposal_agent", make_proposal_agent(reasoner))
    graph.add_node("verify", make_verify(reasoner))
    graph.add_node("review", review)
    graph.add_node("apply", make_apply(tools.subset("apply_rule_version"), job_reader, timeout=apply_timeout, poll_interval=poll_interval))
    graph.add_node("report", make_report())
    graph.add_edge(START, "requirement_agent")
    graph.add_conditional_edges("requirement_agent", route_after_requirement, ["product_impact_agent", "report"])
    graph.add_conditional_edges("product_impact_agent", route_after_impact, ["proposal_agent", "report"])
    graph.add_edge("proposal_agent", "verify")
    graph.add_conditional_edges("verify", route_after_verify, ["proposal_agent", "review"])
    graph.add_conditional_edges("review", route_after_review, ["proposal_agent", "review", "apply", "report"])
    graph.add_edge("apply", "report")
    graph.add_edge("report", END)
    return graph.compile(checkpointer=checkpointer if checkpointer is not None else InMemorySaver(serde=SERDE))
