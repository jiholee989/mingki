"""승인된 규칙만 MCP로 반영 요청하고 큐 작업 완료를 확인한다. 값을 직접 보내지 않는다."""

import time
from app.backend import proposal_rows
from app.schemas import ApplyApproval, ApplyResult, Event
from app.validation import validate_proposal


def approved_rows(proposals, approval):
    approval = ApplyApproval.model_validate(approval)
    keys = approval.proposal_keys
    if len(keys) != len(set(keys)) or any(not key.strip() for key in keys):
        raise ValueError("반영 승인 키가 비어 있거나 중복되었습니다")
    eligible = {}
    for proposal in proposals:
        if proposal.status != "approved" or proposal.verification != "passed" or proposal.generation_error:
            continue
        for row in proposal_rows(proposal):
            if row["impact"] == "change_required":
                key = row["proposalKey"]
                if key in eligible:
                    raise ValueError("같은 상품·규칙이 여러 제안에 중복되었습니다")
                eligible[key] = row
    if not set(keys) <= eligible.keys():
        raise ValueError("검증·승인되지 않았거나 현재 제안에 없는 반영 대상입니다")
    return {key: eligible[key] for key in keys}


PENDING = ("QUEUED", "RUNNING", "RETRYING")


def make_apply(tools, job_reader=None, *, timeout=60, poll_interval=1, max_read_failures=3,
               clock=time.monotonic, sleep=time.sleep):
    """job_reader: 큐 작업 조회 함수 (SpringClient.job). 백엔드 어댑터는 요청마다 다른 콜백 주소를 쓰므로
    그래프를 만들 때가 아니라 재개할 때 config["configurable"]["job_reader"] 로 넘긴다. CLI 검토에는 쓰지 않는다."""
    if timeout <= 0 or poll_interval <= 0:
        raise ValueError("반영 완료 대기 시간과 조회 간격은 양수여야 합니다")

    def apply(state, config=None):
        results, error = [], None
        reader = (config or {}).get("configurable", {}).get("job_reader") or job_reader
        try:
            approval = ApplyApproval.model_validate(state.get("apply_approval"))
            rows = approved_rows(state["proposals"], approval)
            if tools.is_local or reader is None:
                raise ValueError("실제 반영에는 MCP와 백엔드 작업 조회(job_reader) 연결이 필요합니다")
            for proposal in state["proposals"]:
                if any(row["proposalKey"] in rows for row in proposal_rows(proposal)):
                    errors = validate_proposal(state, proposal)
                    if errors:
                        raise ValueError("반영 직전 제안 검사 실패: " + "; ".join(errors))
            # 재개·재시도해도 같은 큐 작업을 가리키도록 승인 ID와 별개로 안정적인 키를 쓴다.
            for key in rows:
                item = ApplyResult(proposal_key=key)
                results.append(item)
                try:
                    response = tools.apply_rule_version(
                        task_id=state["task_id"], approval_id=approval.approval_id,
                        proposal_key=key, idempotency_key=f"{state['task_id']}:apply:{key}")
                    job_id = response.get("jobId")
                    if not isinstance(job_id, str) or not job_id:
                        raise ValueError("반영 접수 응답에 jobId가 없습니다")
                    if any(other.job_id == job_id for other in results if other is not item):
                        raise ValueError("서로 다른 제안에 같은 작업 ID가 반환되었습니다")
                    item.job_id = job_id
                except Exception as exc:
                    # 한 건이 접수에서 거절돼도(이미 바뀐 규칙 등) 나머지 접수와 이미 접수된 작업의 확인은 계속한다.
                    # 결과에는 어느 건이 왜 실패했는지 남고, 최종 판정은 FAILED 다.
                    item.status, item.error = "FAILED", str(exc) or type(exc).__name__
            deadline = clock() + timeout
            read_failures = 0
            while any(item.status in PENDING for item in results):
                for item in results:
                    if item.status not in PENDING:
                        continue
                    try:
                        job = reader(item.job_id)
                    except Exception as exc:
                        # 백엔드가 잠깐 흔들린 것으로 보고 다음 주기에 다시 조회한다. 연속으로 반복되면 포기한다.
                        read_failures += 1
                        if read_failures >= max_read_failures:
                            raise ValueError(f"큐 작업 조회 실패가 {read_failures}회 반복됩니다: {exc}") from exc
                        break
                    read_failures = 0
                    if job.get("id", item.job_id) != item.job_id or job.get("taskId", state["task_id"]) != state["task_id"]:
                        raise ValueError("조회된 큐 작업이 반영 요청과 다릅니다")
                    status = job.get("status")
                    if status not in ("QUEUED", "RUNNING", "RETRYING", "DONE", "DEAD"):
                        raise ValueError(f"{item.job_id}: 알 수 없는 큐 상태입니다")
                    if status == "DONE":
                        result = job.get("result") or {}
                        if result.get("proposalKey") != item.proposal_key or result.get("productId") != rows[item.proposal_key]["productId"]:
                            raise ValueError("완료된 큐 작업의 상품·제안이 요청과 다릅니다")
                        item.result = result
                    elif status == "DEAD":
                        item.error = job.get("lastError") or "큐 작업이 DEAD로 종료되었습니다"
                    item.status = status
                pending = [item for item in results if item.status in PENDING]
                if not pending:
                    break
                remaining = deadline - clock()
                if remaining <= 0:
                    for item in pending:
                        item.status, item.error = "TIMEOUT", "반영 작업 완료 확인 시간 초과"
                    break
                sleep(min(poll_interval, remaining))
            failures = [f"{item.proposal_key}: {item.error}" for item in results if item.status != "DONE"]
            error = "; ".join(failures) or None
        except Exception as exc:
            # 일부 작업은 이미 접수·완료됐을 수 있으므로 기록을 보존하고 성공으로 보고하지 않는다.
            error = str(exc) or type(exc).__name__
        message = f"규칙 {len(results)}건 반영 완료" if not error else "반영 실패: " + error
        return {"apply_results": results, "apply_error": error,
                "events": [Event(node="apply", message=message)]}

    return apply
