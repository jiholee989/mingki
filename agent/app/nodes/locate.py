from pathlib import PurePosixPath
from app.schemas import Event


def make_locate_agent(tools, reasoner):
    def locate_agent(state):
        req_ids = {r.id for r in state["requirements"]}
        specs, seen = [], set()
        for item in reasoner.locate(state, tools):
            path = PurePosixPath(item.file)
            if (
                item.requirement_id not in req_ids
                or path.is_absolute()
                or ".." in path.parts
            ):
                raise ValueError("영향 위치의 요건 또는 경로가 올바르지 않습니다")
            # 같은 코드가 여러 요건에 영향을 받는 관계를 보존한다.
            key = (item.requirement_id, item.file, item.line, item.symbol)
            if key in seen:
                continue
            specs.append(item.model_copy(update={
                "id": f"SPEC-{len(specs)+1}",
                "is_target": item.is_target and not item.needs_review,
            }))
            seen.add(key)
        return {
            "change_specs": specs,
            "events": [
                Event(
                    node="locate_agent",
                    message=f"영향 후보 {len(specs)}곳: 근거와 함께 검토",
                )
            ],
        }

    return locate_agent
