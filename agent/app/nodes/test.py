import ast
from app.schemas import Event


def make_test_agent(tools, reasoner):
    def test_agent(state):
        req_ids = {r.id for r in state["requirements"]}
        cases = reasoner.tests(state, tools)
        seen = set()
        for case in cases:
            if case.requirement_id not in req_ids or case.id in seen:
                raise ValueError("테스트의 요건 또는 ID가 올바르지 않습니다")
            if case.code:
                ast.parse(case.code)  # 실행은 하지 않는다. 격리된 code-mcp가 담당한다.
            seen.add(case.id)
        return {
            "test_cases": cases,
            "events": [
                Event(node="test_agent", message=f"테스트 명세 {len(cases)}건 고정 / 실행 코드 {sum(bool(t.code) for t in cases)}건")
            ],
        }

    return test_agent
