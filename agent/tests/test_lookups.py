"""모델이 고른 조회를 하네스가 실행한다: 허용된 규정 · 버전만, 개수 제한, 실패는 자료 없음, 기록 · 판단 자료에 반영."""

from app.graph import build_graph
from app.lookups import MAX_LOOKUPS, run_lookups
from app.runner import AgentRunner
from app.schemas import Lookup
from app.tools.local import LocalTools
from tests.test_graph import DsrReasoner, ThreeProductTools
from tests.test_server import started

RELATED = [{"regulation_id": "dsr-management", "version": "v2", "title": "가계대출 DSR 관리기준"},
           {"regulation_id": "senior-protection", "version": "v1", "title": "고령 금융소비자 보호기준"}]


def article(regulation_id, article_id, reason="확인"):
    return Lookup(tool="get_article", regulation_id=regulation_id, article_id=article_id, query=None, reason=reason)


def search(query, regulation_id=None):
    return Lookup(tool="search_regulation", regulation_id=regulation_id, article_id=None, query=query, reason="검색")


def test_chosen_article_is_fetched_with_the_related_version():
    found, gaps = run_lookups(LocalTools(), [article("dsr-management", "10")], RELATED, set())
    assert [(a["uri"], a["regulation_id"], a["version"]) for a in found] == [("reg://dsr-management/v2/10", "dsr-management", "v2")]
    assert "소액신용대출" in found[0]["text"] and gaps == []


def test_only_related_regulations_and_new_articles_are_used():
    known = {"reg://dsr-management/v2/10"}
    lookups = [article("dsr-management", "10"),        # 이미 문맥에 있음 → 다시 넣지 않음
               article("credit-loan-ops", "8"),       # 바뀐 규정은 이미 문맥에 있고 고를 대상이 아님
               article("unknown", "1")]
    found, gaps = run_lookups(LocalTools(), lookups, RELATED, known)
    assert found == [] and len(gaps) == 2


def test_search_keeps_only_related_versions_and_a_few_hits():
    found, _ = run_lookups(LocalTools(), [search("소액신용대출 적용 예외")], RELATED, set())
    assert found and len(found) <= 3
    assert {a["regulation_id"] for a in found} <= {"dsr-management", "senior-protection"}
    assert ("dsr-management", "10") in {(a["regulation_id"], a["article_id"]) for a in found}


def test_failed_lookup_becomes_a_data_gap_and_the_count_is_capped():
    class Broken(LocalTools):
        def get_article(self, *args):
            raise TimeoutError("MCP 응답 없음")
    found, gaps = run_lookups(Broken(), [article("dsr-management", "10")], RELATED, set())
    assert found == [] and "MCP 응답 없음" in gaps[0]
    many = [article("dsr-management", str(n)) for n in range(1, 10)]
    found, _ = run_lookups(LocalTools(), many, RELATED, set())
    assert len(found) == MAX_LOOKUPS


class LooksUpExemption(DsrReasoner):
    """DSR 요건을 판단하기 전에 DSR 관리기준 제10조(적용 예외)를 고른다."""
    def __init__(self):
        super().__init__()
        self.impact_context = None

    def choose_lookups(self, requirement, products, rules, regulation_context, related):
        return [article("dsr-management", "10", reason="소액대출 DSR 적용 예외 확인")]

    def product_impacts(self, requirements, products, rules, regulation_context=None, documents=None, data_gaps=None):
        self.impact_context = regulation_context
        return super().product_impacts(requirements, products, rules, regulation_context, documents, data_gaps)


def test_chosen_articles_reach_impact_judgment_and_later_steps():
    reasoner = LooksUpExemption()
    out = AgentRunner(build_graph(ThreeProductTools(), reasoner)).start("T1", "credit-loan-ops", article_ids=["8"])
    uris = {a["uri"] for a in reasoner.impact_context}
    assert "reg://dsr-management/v2/10" in uris and "reg://credit-loan-ops/v4/8" in uris
    assert "reg://dsr-management/v2/3" not in uris                 # 고르지 않은 다른 규정 조항은 없다
    assert "reg://dsr-management/v2/10" in {a["uri"] for a in out["regulation_context"]}   # 제안 · 검사도 같은 자료


def test_choice_and_reason_are_recorded_before_the_tool_call():
    _, spring, _ = started(reasoner=LooksUpExemption())
    events = [(name, body) for kind, name, body in spring.calls if kind == "event"]
    plan = next(i for i, (name, _) in enumerate(events) if name == "TOOL_PLAN")
    assert events[plan][1]["lookups"][0] == {"tool": "get_article", "regulationId": "dsr-management", "articleId": "10",
                                             "query": None, "reason": "소액대출 DSR 적용 예외 확인",
                                             "regulationTitle": "가계대출 DSR 관리기준", "articleTitle": "적용 예외"}   # 화면 표시용 이름
    call = next(i for i, (name, body) in enumerate(events) if name == "TOOL_START" and body.get("tool") == "get_article")
    assert plan < call and events[call][1]["node"] == "product_impact_agent"
