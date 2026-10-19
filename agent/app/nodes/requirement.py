import re
from datetime import date

from app.data import article_label
from app.schemas import Event, Requirement
from app.state import RippleState

# LLM 자리: 조항 → 정책 키 해석. 스텁은 시연 데이터의 조항만 안다.
_TARGET_KEYS = {"8": "DSR_LIMIT", "15": "SENIOR_AGE", "15-2": "SENIOR_EXPLANATION"}

_ARTICLE_REF = re.compile(r"제(\d+)조(?:의(\d+))?")


def parse_numbers(text: str | None) -> list[str]:
    """'40%' → '0.40', '만 65세' → '65'. 비율은 소수 둘째 자리로 맞춘다."""
    return [f"{float(n) / 100:.2f}" if pct else n for n, pct in re.findall(r"(\d+(?:\.\d+)?)(%)?", text or "")]


def _referenced_articles(text: str) -> set[str]:
    return {f"{n}-{s}" if s else n for n, s in _ARTICLE_REF.findall(text)}


def make_requirement_agent(tools):
    """신·구 조항 비교 → 요건 구조화. (LLM 자리, 지금은 규칙 기반 스텁)

    diff 자체는 도구(코드)가 결정적으로 만든다. 여기서는 실질 변경 판단과 의미 해석만 한다.
    - 본문 조항: 수치가 바뀌었거나 신설이면 실질 변경, 문장만 다듬었으면 제외
    - 부칙: 요건이 아니라 해당 조항을 언급하는 요건의 경과조치로 붙인다
    """

    def requirement_agent(state: RippleState) -> dict:
        diff = tools.diff_versions(state["regulation_id"], state["old_version"], state["new_version"])
        effective = date.fromisoformat(diff["effective_from"]) if diff.get("effective_from") else None
        supplementary = [c for c in diff["changes"] if c["article_id"].startswith("supp-") and c["new_text"]]

        requirements = []
        for c in diff["changes"]:
            aid = c["article_id"]
            if aid.startswith("supp-"):
                continue
            old_nums, new_nums = parse_numbers(c["old_text"]), parse_numbers(c["new_text"])
            if c["change"] == "modified" and old_nums == new_nums:
                continue  # 자구 수정
            changed = [(o, n) for o, n in zip(old_nums, new_nums) if o != n]
            old_value, new_value = changed[0] if changed else (None, None)

            transitional = [
                f"{article_label(s['article_id'])}({s['title']}) {s['new_text']}"
                for s in supplementary
                if aid in _referenced_articles(s["new_text"])
            ]
            label = f"{article_label(aid)}({c['title']})"
            requirements.append(
                Requirement(
                    id=f"REQ-{aid}",
                    article_id=aid,
                    article=label,
                    article_ref=f"reg://{state['regulation_id']}/{state['new_version']}/{aid}",
                    change="added" if c["change"] == "added" else "modified",
                    summary=f"{label} 신설" if c["change"] == "added" else f"{label} {old_value} → {new_value}",
                    target=_TARGET_KEYS.get(aid, f"ARTICLE_{aid}"),
                    old_value=old_value,
                    new_value=new_value,
                    old_text=c["old_text"],
                    new_text=c["new_text"],
                    effective_date=effective,
                    transitional="\n".join(transitional) or None,
                )
            )
        return {
            "requirements": requirements,
            "events": [
                Event(node="requirement_agent", message=f"실질 변경 {len(requirements)}건 / 바뀐 조항 {len(diff['changes'])}건")
            ],
        }

    return requirement_agent


def route_after_requirement(state: RippleState) -> str:
    return "confirm_requirements" if state.get("requirements") else "report"
