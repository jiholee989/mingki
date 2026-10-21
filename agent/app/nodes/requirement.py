from datetime import date, timedelta
from app.schemas import Event, Requirement
from app.tools.base import recorder_of, recording


def make_requirement_agent(tools, reasoner):
    def requirement_agent(state, config=None):
        belt = recording(tools, recorder_of(config), "requirement_agent")
        diff = belt.diff_versions(
            state["regulation_id"], state["old_version"], state["new_version"]
        )
        # 바뀌지 않은 적용 범위·정의·부칙도 판단에 필요하다.
        context = belt.get_regulation_context(state["regulation_id"], state["new_version"])
        articles = context["articles"]
        diff["regulation_context"] = articles
        primary = [a for a in articles if a["regulation_id"] == state["regulation_id"]]
        supplementary = "\n".join(f"{a['title']}: {a['text']}" for a in primary if a["article_id"].startswith("supp-"))
        if state.get("article_ids"):
            requested = set(state["article_ids"])
            known = {c["article_id"] for c in diff["changes"] if not c["article_id"].startswith("supp-")}
            if not requested <= known:
                raise ValueError("변경 본문에 없는 조항을 선택했습니다")
            diff["changes"] = [c for c in diff["changes"] if c["article_id"] in requested or c["article_id"].startswith("supp-")]
        snapshot_date = ((date.fromisoformat(diff["effective_from"]) - timedelta(days=1)).isoformat()
                         if diff.get("effective_from") else date.today().isoformat())
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
                transitional=supplementary or item.transitional,
                effective_date=(date.fromisoformat(diff["effective_from"])
                                if diff.get("effective_from") else item.effective_date),
            )
            requirements.append(Requirement.model_validate(data))
            seen.add(item.id)
        return {
            "requirements": requirements,
            "regulation_context": articles,
            "related_regulations": context.get("related", []),
            "data_gaps": context["data_gaps"],
            "snapshot_date": snapshot_date,
            "mode": "llm" if tools.is_local else "live",
            "events": [
                Event(
                    node="requirement_agent", message=f"변경 요건 {len(requirements)}건"
                )
            ],
        }

    return requirement_agent


def route_after_requirement(state):
    return "product_impact_agent" if state.get("requirements") else "report"
