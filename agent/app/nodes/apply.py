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


def make_apply(tools, job_reader, *, timeout=60, poll_interval=1, clock=time.monotonic, sleep=time.sleep):
    """job_reader는 백엔드 어댑터의 SpringClient.job을 주입한다. CLI 검토에는 쓰지 않는다."""
    if timeout <= 0 or poll_interval <= 0:
        raise ValueError("반영 완료 대기 시간과 조회 간격은 양수여야 합니다")

    def apply(state):
        results, error = [], None
        try:
            approval = ApplyApproval.model_validate(state.get("apply_approval"))
            rows = approved_rows(state["proposals"], approval)
            if tools.is_local or job_reader is None:
                raise ValueError("실제 반영에는 MCP와 백엔드 작업 조회(job_reader) 연결이 필요합니다")
            for proposal in state["proposals"]:
                if any(row["proposalKey"] in rows for row in proposal_rows(proposal)):
                    errors = validate_proposal(state, proposal)
                    if errors:
                        raise ValueError("반영 직전 제안 검사 실패: " + "; ".join(errors))
            # 재개·재시도해도 같은 큐 작업을 가리키도록 승인 ID와 별개로 안정적인 키를 쓴다.
            for key in rows:
                response = tools.apply_rule_version(
                    task_id=state["task_id"], approval_id=approval.approval_id,
                    proposal_key=key, idempotency_key=f"{state['task_id']}:apply:{key}")
                job_id = response.get("jobId")
                if not isinstance(job_id, str) or not job_id:
                    raise ValueError(f"{key}: 반영 접수 응답에 jobId가 없습니다")
                if any(item.job_id == job_id for item in results):
                    raise ValueError("서로 다른 제안에 같은 작업 ID가 반환되었습니다")
                results.append(ApplyResult(proposal_key=key, job_id=job_id))
            deadline = clock() + timeout
            while any(item.status in ("QUEUED", "RUNNING", "RETRYING") for item in results):
                for item in results:
                    if item.status not in ("QUEUED", "RUNNING", "RETRYING"):
                        continue
                    job = job_reader(item.job_id)
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
                pending = [item for item in results if item.status in ("QUEUED", "RUNNING", "RETRYING")]
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
