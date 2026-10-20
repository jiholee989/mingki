from datetime import date
from app.schemas import Event, Requirement


def make_requirement_agent(tools, reasoner):
    def requirement_agent(state):
        diff = tools.diff_versions(
            state["regulation_id"], state["old_version"], state["new_version"]
        )
        changes = {c["article_id"]: c for c in diff["changes"]}
        requirements, seen = [], set()
        for item in reasoner.requirements(diff):
            if item.article_id not in changes or item.id in seen:
                raise ValueError("요건의 근거 조항 또는 ID가 올바르지 않습니다")
            source = changes[item.article_id]
            if item.article_id.startswith("supp-"):
                continue
            # 원문과 출처는 모델 출력 대신 실제 비교 결과를 사용한다.
            data = item.model_dump()
            data.update(
                article_ref=source.get("new_uri") or source.get("old_uri"),
                old_text=source["old_text"],
                new_text=source["new_text"],
                change=source["change"],
                effective_date=item.effective_date
                or (
                    date.fromisoformat(diff["effective_from"])
                    if diff.get("effective_from")
                    else None
                ),
            )
            requirements.append(Requirement.model_validate(data))
            seen.add(item.id)
        return {
            "requirements": requirements,
            "demo": reasoner.is_demo or tools.is_mock,
            "llm_used": not reasoner.is_demo,
            "events": [
                Event(
                    node="requirement_agent", message=f"변경 요건 {len(requirements)}건"
                )
            ],
        }

    return requirement_agent


def route_after_requirement(state):
    return "locate_agent" if state.get("requirements") else "report"
