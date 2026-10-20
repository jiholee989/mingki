"""Spring 전송 계약 변환. HTTP 호출/DB 접근 없이 테스트할 수 있는 연결 지점."""

from pydantic import BaseModel, ConfigDict, Field

class DocumentInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    side: str
    version_label: str = Field(alias="versionLabel")
    filename: str = ""
    sha256: str = ""


class RunRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    task_id: str = Field(alias="taskId")
    thread_id: str = Field(alias="threadId")
    documents: list[DocumentInfo]
    callback_base_url: str | None = Field(default=None, alias="callbackBaseUrl")

    def to_input(self, regulation_id):
        # regulation_id는 업로드 원문을 등록한 MCP의 식별자를 전달받는다.
        versions = {doc.side: doc.version_label for doc in self.documents}
        if (
            set(versions) != {"OLD", "NEW"}
            or len(self.documents) != 2
            or not regulation_id
        ):
            raise ValueError("구·신 문서 정보와 MCP 규정 식별자가 필요합니다")
        return {
            "task_id": self.task_id,
            "thread_id": self.thread_id,
            "regulation_id": regulation_id,
            "old_version": versions["OLD"],
            "new_version": versions["NEW"],
        }


class ResumeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    task_id: str = Field(alias="taskId")
    thread_id: str = Field(alias="threadId")
    step: str
    decision: str
    approval_id: int | None = Field(default=None, alias="approvalId")
    comment: str | None = None
    payload: dict = Field(default_factory=dict)

    def to_decision(self):
        if self.step == "REQUIREMENTS":
            if self.decision not in ("CONFIRM", "HOLD"):
                raise ValueError("요건 결정은 CONFIRM/HOLD입니다")
            return {
                "action": "approve" if self.decision == "CONFIRM" else "reject",
                "confirmed_req_keys": self.payload.get("confirmedReqKeys", []),
                "comment": self.comment,
            }
        if self.step != "REVIEW" or self.decision not in (
            "APPROVE",
            "REJECT",
            "REQUEST_CHANGES",
        ):
            raise ValueError("알 수 없는 승인 단계/결정입니다")
        return {
            "action": {
                "APPROVE": "approve",
                "REJECT": "reject",
                "REQUEST_CHANGES": "request_changes",
            }[self.decision],
            "approval_id": self.approval_id,
            "comment": self.comment,
            "excluded_spec_keys": self.payload.get("excludedSpecKeys", []),
        }


def requirements_payload(items):
    return {
        "items": [
            {
                "reqKey": r.id,
                "summary": r.summary,
                "target": r.target,
                "effectiveDate": r.effective_date.isoformat()
                if r.effective_date
                else None,
                "transitional": r.transitional,
                "articleRef": r.article_ref,
                "oldText": r.old_text,
                "newText": r.new_text,
                "detail": r.model_dump(mode="json"),
            }
            for r in items
        ]
    }


def change_specs_payload(items):
    kinds = {"product_rule": "PRODUCT", "new": "CODE"}
    return {
        "items": [
            {
                "specKey": s.id,
                "reqKey": s.requirement_id,
                "locationKind": kinds.get(s.kind, s.kind.upper()),
                "filePath": s.file,
                "symbol": s.symbol,
                "lineNo": s.line,
                "snippet": s.snippet,
                "changeType": (
                    "NEW"
                    if s.kind == "new"
                    else "DB"
                    if s.kind in ("db", "product_rule")
                    else "LOGIC"
                    if s.kind == "code"
                    else "VALUE"
                )
                if s.is_target
                else None,
                "target": s.is_target,
                "reason": s.reason,
                "bundle": f"B:{s.file}",
                "detail": {},
            }
            for s in items
        ]
    }


def patches_payload(items):
    # 티켓 명세/시연은 코드 패치가 아니다. 백엔드의 PASSED 행으로 저장하지 않는다.
    return {
        "items": [
            {
                "bundle": p.bundle_id,
                "round": p.round,
                "filePath": p.files[0],
                "specKeys": p.spec_ids,
                "diff": p.diff,
                "verifyStatus": {"passed": "PASSED", "patch_failed": "FAILED"}.get(
                    p.status, "PENDING"
                ),
                "verifyLog": "\n".join(p.errors),
                "detail": {"proposal": p.proposal},
            }
            for p in items
            if p.status != "ticket_only" and p.diff
        ]
    }


def test_cases_payload(items):
    return {
        "items": [
            {
                "testKey": t.id,
                "reqKey": t.requirement_id,
                "name": t.description,
                "kind": t.kind.upper(),
                "code": t.code,
                "detail": {"inputs": t.inputs, "expected": t.expected},
            }
            for t in items
            if t.code
        ]
    }
