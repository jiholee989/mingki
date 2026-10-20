"""business-mcp: 상품 · 상품 규칙 · 계약 · DB 스키마 조회 (Spring /internal/** 경유) + 상품 규칙 반영 · 작업 상태.

API 계약은 docs/BACKEND_API.md 9 · 10절, 예시는 docs/contracts/. 응답 키는 백엔드 그대로 camelCase.

실행:
    uv run python -m business_mcp.server          # HTTP  http://127.0.0.1:8003/mcp
    uv run python -m business_mcp.server --stdio
"""

import os
import re
import sys
from datetime import date
from typing import Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from business_mcp.backend import Backend, BackendError

mcp = FastMCP(
    "business-mcp",
    instructions=(
        "리플은행 개인신용대출의 상품 · 상품 규칙 · 계약 데이터 (Spring 백엔드 응답 그대로). "
        "어떤 규칙 키가 있는지는 list_rule_keys로 먼저 본다. "
        "상품 규칙이 그날 유효한지는 effectiveFrom ≤ 기준일 ≤ effectiveTo(없으면 무한)로 판단한다 "
        "(get_product_rules(as_of=기준일)). effectiveTo가 null이어도 시작 전일 수 있다. "
        "apply_rule_version은 사용자 확인(승인) 뒤 apply 단계에서만 쓰고, 결과는 get_job으로 기다린다. "
        "create_work_ticket은 옛 흐름용이다 (BACKEND_API 10.7 정리 예정)."
    ),
)
backend = Backend()
_PRODUCT_ID = re.compile(r"^[A-Za-z0-9_-]{1,10}$")
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except BackendError as e:
        raise ToolError(str(e)) from e


# ---------- 읽기 ----------

@mcp.tool(annotations={"readOnlyHint": True})
def get_products(status: Literal["ON_SALE", "SALE_ENDED"] | None = None) -> list[dict]:
    """상품 목록.

    Args:
        status: ON_SALE(판매 중) | SALE_ENDED(판매 중단). 생략하면 전체

    Returns:
        [{productId, name, description, repaymentTypes, minTermMonths, maxTermMonths, status}]
    """
    products = _list_of_dicts(_call(backend.get, "/internal/products", {"status": status}), "상품")
    return [p for p in products if status is None or p.get("status") == status]


def _list_of_dicts(data, what: str) -> list[dict]:
    if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
        raise ToolError(f"백엔드 {what} 응답이 목록 형식이 아닙니다: {str(data)[:100]}")
    return data


def _iso(value) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except (TypeError, ValueError):
        return False


def _rules(data) -> list[dict]:
    """상품 규칙 응답이 계약(BACKEND_API 9 · 10.5)과 맞는지 확인. 날짜 계산 전에 어떤 행이 왜 틀렸는지 알린다."""
    for r in _list_of_dicts(data, "상품 규칙"):
        bad = [f for f in ("ruleKey", "unit") if not isinstance(r.get(f), str) or not r.get(f)]
        bad += [] if _iso(r.get("effectiveFrom")) else ["effectiveFrom"]
        bad += [] if r.get("effectiveTo") is None or _iso(r.get("effectiveTo")) else ["effectiveTo"]
        if bad:
            raise ToolError(f"백엔드 상품 규칙 응답 형식 오류: {r.get('ruleId', '?')}의 {', '.join(bad)} 값이 잘못됐습니다")
    return data


def _today() -> date:
    return date.today()


def _as_of(value: str | None) -> date | None:
    if value is None:
        return None
    if value == "today":
        return _today()
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ToolError(f"잘못된 as_of: {value!r} (YYYY-MM-DD 또는 \"today\")") from None


def _period(rule: dict, day: date) -> Literal["active", "closed", "upcoming"]:
    """그날 기준 행의 상태. 유효 = effectiveFrom ≤ day ≤ effectiveTo(없으면 무한) (BACKEND_API 10.5).

    effectiveTo == null 만으로 판단하면 틀린다. 반영 직후 기존 행은 effectiveTo가 미래(아직 유효)이고,
    새 행은 effectiveFrom이 미래(아직 시작 전)인데 effectiveTo는 null이다.
    """
    if date.fromisoformat(rule["effectiveFrom"]) > day:
        return "upcoming"
    end = rule.get("effectiveTo")
    return "closed" if end is not None and date.fromisoformat(end) < day else "active"


@mcp.tool(annotations={"readOnlyHint": True})
def get_product_rules(
    rule_key: str | None = None, product_id: str | None = None, as_of: str | None = None
) -> list[dict]:
    """상품 규칙 (rule_key · product_id로 좁힐 수 있음, 둘 다 없으면 전체).

    같은 숫자라도 rule_key가 다르면 의미가 다르다 (예: DSR_LIMIT 0.40 vs MORTGAGE_LTV_LIMIT 0.40).
    어떤 키가 있는지 모르면 list_rule_keys를 먼저 본다.

    Args:
        rule_key: 규칙 키 (예: "DSR_LIMIT", "ELIGIBLE_MIN_AGE")
        product_id: 상품 ID (예: "P002")
        as_of: 그날 유효한 행만 (YYYY-MM-DD 또는 "today"). effectiveFrom ≤ as_of ≤ effectiveTo(없으면 무한).
            생략하면 종료된 옛 버전 · 시작 전 행까지 전체. 시행일 기준으로 보려면 시행일을 넣는다

    Returns:
        [{ruleId, productId, ruleKey, value, unit, effectiveFrom, effectiveTo}]
        unit: ratio | percent | percent_point | krw | age | score | bool | years | months … (상품마다 다를 수 있음)
    """
    day = _as_of(as_of)
    params = {"key": rule_key, "asOf": day.isoformat() if day else None}
    if rule_key == "":
        raise ToolError("rule_key가 비어 있습니다. 전체를 보려면 생략합니다")
    if product_id is not None:
        # URL 경로에 들어가므로 ../ 같은 값으로 다른 /internal API에 닿지 못하게 막는다. 빈 값도 전체 조회로 새지 않게 거절
        if not _PRODUCT_ID.match(product_id):
            raise ToolError(f"잘못된 product_id: {product_id!r} (예: P002). 전체를 보려면 생략합니다")
        rules = _rules(_call(backend.get, f"/internal/products/{product_id}/rules", params))
    else:
        rules = _rules(_call(backend.get, "/internal/product-rules", params))
    # 백엔드가 asOf · key를 아직 지원하지 않아도 결과가 같도록 한 번 더 거른다 (지원하면 그대로 통과)
    return [
        r for r in rules
        if (rule_key is None or r.get("ruleKey") == rule_key) and (day is None or _period(r, day) == "active")
    ]


@mcp.tool(annotations={"readOnlyHint": True})
def list_rule_keys(as_of: str | None = None) -> list[dict]:
    """상품 규칙 키 목록과 어느 상품에 있는지. 어떤 규칙이 있는지 모를 때 먼저 본다.

    같은 개념이라도 상품마다 키 이름이나 단위가 다를 수 있다 (예: DSR_LIMIT · MAX_DSR_RATIO,
    EXPLANATION_RECORD_YEARS · EXPLANATION_RECORD_MONTHS). 키 이름만 보지 말고 단위와 상품을 함께 본다.

    Args:
        as_of: 기준일 (YYYY-MM-DD). 생략하면 오늘

    Returns:
        [{ruleKey, units: [unit], productIds: [as_of에 유효한 행이 있는 상품],
          activeRows, closedRows, upcomingRows(아직 시작 전, 반영 직후 생김)}] ruleKey 순
    """
    day = _as_of(as_of) or _today()
    keys = _list_of_dicts(_call(backend.get, "/internal/product-rules/keys", {"asOf": day.isoformat()}), "규칙 키")
    for k in keys:
        if not isinstance(k.get("ruleKey"), str) or not k["ruleKey"]:
            raise ToolError(f"백엔드 규칙 키 응답 형식 오류: ruleKey가 없는 항목이 있습니다: {str(k)[:100]}")
    return keys


@mcp.tool(annotations={"readOnlyHint": True})
def get_db_schema() -> list[dict]:
    """샘플 업무 테이블(products, product_rules, loan_contracts)의 컬럼 정보.

    Returns:
        [{table, columns: [{name, type, nullable}]}]
    """
    return _call(backend.get, "/internal/db/schema")


@mcp.tool(annotations={"readOnlyHint": True})
def get_contract_impact(age_from: int = 0, age_to: int = 200, applied_before: str | None = None) -> dict:
    """신청일 기준 만 나이가 [age_from, age_to]인 유효 계약 · 신청 (경과조치 영향 확인용).

    거절 건과 만기 지난 계약은 빠진다. applied_before(시행일)보다 먼저 신청한 건은
    grandfathered=true (종전 기준 유지)로 센다.

    Args:
        age_from: 최소 나이 (예: 60)
        age_to: 최대 나이 (예: 64)
        applied_before: 시행일 YYYY-MM-DD (예: "2026-12-01")

    Returns:
        {ageFrom, ageTo, total, byProduct, appliedBefore?, grandfathered?,
         contracts: [{contractId, productId, status, appliedAt, ageAtApplication, grandfathered?}]}
    """
    return _call(
        backend.get,
        "/internal/contracts/impact",
        {"ageFrom": age_from, "ageTo": age_to, "appliedBefore": applied_before},
    )


# ---------- 쓰기 (승인 필요) ----------

def _uuid(value: str, name: str) -> str:
    # URL 경로 · 요청 본문에 들어가므로 형식부터 확인한다 (../ 같은 값으로 다른 API에 닿지 못하게)
    if not isinstance(value, str) or not _UUID.match(value):
        raise ToolError(f"잘못된 {name}: {value!r} (UUID 형식, 예: 7c7593e7-2a9c-47b3-8607-23f690f223d4)")
    return value.lower()


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True})
def apply_rule_version(task_id: str, approval_id: int, proposal_key: str, idempotency_key: str | None = None) -> dict:
    """사용자가 반영으로 고른 제안 하나를 상품 규칙 새 버전으로 등록해 달라고 요청한다 (승인 필요, 대기열 작업).

    값은 보내지 않는다. 백엔드가 저장된 제안에서 지금 값 · 제안 값 · 단위 · 시행일을 꺼내 쓰므로,
    사용자가 확인한 값과 다른 값은 들어갈 수 없다. 기존 행은 시행일 전날로 닫히고 새 행이 시행일부터 생긴다.
    결과는 get_job(jobId)으로 DONE · DEAD가 될 때까지 확인한다.

    거절 (백엔드 403 · 409): 최신 REVIEW/APPROVE 승인이 아님, 작업 상태가 PUBLISHING이 아님,
    승인 때 반영으로 고르지 않은 제안, 근거 검사를 통과하지 않은 제안, 지금 값이 제안 때와 다름("이미 바뀐 규칙").
    같은 idempotency_key로 다시 부르면 새로 만들지 않고 duplicate=true로 기존 jobId를 돌려준다.

    Args:
        task_id: 분석 작업 ID (UUID)
        approval_id: 검토 승인 기록 ID
        proposal_key: 반영할 제안 키 (예: "P001:DSR_LIMIT")
        idempotency_key: 생략하면 "{task_id}:apply:{proposal_key}"

    Returns:
        {jobId, status: "QUEUED", duplicate}
    """
    task_id = _uuid(task_id, "task_id")
    if not proposal_key or not proposal_key.strip():
        raise ToolError("proposal_key가 비어 있습니다 (예: P001:DSR_LIMIT)")
    return _call(backend.post, "/internal/product-rules/versions", {
        "taskId": task_id,
        "approvalId": approval_id,
        "proposalKey": proposal_key,
        "idempotencyKey": idempotency_key or f"{task_id}:apply:{proposal_key}",
    })


@mcp.tool(annotations={"readOnlyHint": True})
def get_job(job_id: str) -> dict:
    """대기열 작업 상태 (apply_rule_version 결과를 기다릴 때 반복 호출한다).

    status: QUEUED → RUNNING → DONE, 실패하면 RETRYING을 거쳐 재시도하고 3번 실패하면 DEAD.
    "이미 바뀐 규칙"처럼 다시 해도 같은 실패는 재시도 없이 바로 DEAD가 된다 (lastError에 이유).

    Args:
        job_id: apply_rule_version이 돌려준 jobId (UUID)

    Returns:
        {jobId, type, status, attempts, result, lastError}
        반영 result: {proposalKey, productId, closedRuleId(새 규칙이면 null), newRuleId, effectiveFrom}
    """
    job = _call(backend.get, f"/internal/jobs/{_uuid(job_id, 'job_id')}")
    if not isinstance(job, dict) or "status" not in job:
        raise ToolError(f"백엔드 작업 응답 형식 오류: {str(job)[:100]}")
    return {
        "jobId": job.get("id", job_id),
        "type": job.get("type"),
        "status": job["status"],
        "attempts": job.get("attempts"),
        "result": job.get("result"),
        "lastError": job.get("lastError"),
    }


@mcp.tool(annotations={"readOnlyHint": False, "idempotentHint": True})
def create_work_ticket(
    task_id: str,
    approval_id: int,
    idempotency_key: str,
    title: str,
    description: str | None = None,
    type: Literal["CODE", "CONFIG", "DB", "DOC", "TEST"] = "CODE",
    target_ref: str | None = None,
    spec_keys: list[str] | None = None,
    assignee: str | None = None,
) -> dict:
    """작업 티켓 생성 요청 (승인 필요). 백엔드가 approval_id를 다시 검증하고 큐에 넣는다.

    거절 조건 (403/409): 같은 작업의 최신 REVIEW/APPROVE 승인이 아님, 작업 상태가 PUBLISHING이 아님,
    spec_keys에 승인 때 제외한 위치가 있음. 같은 idempotency_key로 다시 부르면 새로 만들지 않는다.

    Args:
        task_id: 분석 작업 ID (UUID)
        approval_id: 검토 · 승인 기록 ID
        idempotency_key: 예: "{task_id}:ticket:S1"
        title: 티켓 제목
        description: 본문
        type: CODE | CONFIG | DB | DOC | TEST
        target_ref: 대상 위치 (예: "src/loan/eligibility.py:21")
        spec_keys: 대상 변경 명세 ID 목록
        assignee: 담당자

    Returns:
        {jobId, status: "QUEUED", duplicate}. 완료는 GET /internal/jobs/{jobId}로 확인한다.
    """
    return _call(backend.post, "/internal/work-tickets", {
        "taskId": task_id,
        "approvalId": approval_id,
        "idempotencyKey": idempotency_key,
        "title": title,
        "description": description,
        "type": type,
        "targetRef": target_ref,
        "specKeys": spec_keys or [],
        "assignee": assignee,
    })


if __name__ == "__main__":
    if "--stdio" in sys.argv:
        mcp.run(transport="stdio")
    else:
        mcp.run(
            transport="http",
            host=os.environ.get("HOST", "127.0.0.1"),
            port=int(os.environ.get("PORT", 8003)),
            path="/mcp",
        )
