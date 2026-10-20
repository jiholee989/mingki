"""Spring ↔ Agent HTTP 어댑터. 계약은 docs/BACKEND_API.md 6절.

    POST /run     {taskId, threadId, title, documents, callbackBaseUrl}         → 202
    POST /resume  {taskId, threadId, step, decision, approvalId, payload, ...} → 202

둘 다 바로 202를 돌려주고 그래프는 백그라운드에서 돌린다. 진행 상황은 SpringBridge가 콜백으로 보낸다.

실행: uv run uvicorn app.server:create_app --factory --port 8000
"""

import hashlib
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

# agent/.env 를 읽는다. 이미 있는 환경 변수(compose 등)가 우선한다. app.* 를 import 하기 전에 읽어야 한다.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from fastapi import FastAPI, Header, HTTPException  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from app.backend import ResumeRequest, RunRequest  # noqa: E402
from app.bridge import SpringBridge  # noqa: E402
from app.data import DATA_DIR  # noqa: E402
from app.runner import DecisionError, NotWaitingError  # noqa: E402
from app.spring import INTERNAL_TOKEN, SpringClient  # noqa: E402

log = logging.getLogger(__name__)

AGENT_MODE = os.getenv("AGENT_MODE", "llm")
REGULATION_ID = os.getenv("REGULATION_ID", "credit-loan-ops")


def build_runner(mode=AGENT_MODE):
    """run.py와 같은 모드. llm=실제 모델+로컬 자료, live=실제 모델+MCP. 둘 다 실제 LLM 이 필요하다."""
    from app.checkpoint import make_checkpointer
    from app.graph import build_graph
    from app.llm import LlmReasoner
    from app.runner import AgentRunner

    if mode == "live":
        from app.tools.mcp_client import McpTools

        tools = McpTools()
    elif mode == "llm":
        from app.tools.local import LocalTools

        tools = LocalTools()
    else:
        raise ValueError(f"알 수 없는 AGENT_MODE: {mode} (llm | live)")
    return AgentRunner(build_graph(tools, LlmReasoner(), checkpointer=make_checkpointer()))


def check_documents(documents, regulation_id, data_dir=DATA_DIR):
    """업로드한 원문이 분석할 원문과 같은지 확인한다. 원문 파일이 없는 환경이면 건너뛴다.

    Agent는 업로드 본문이 아니라 regulation-mcp에 등록된 {regulation_id}/{version}을 분석한다.
    """
    for doc in documents:
        path = data_dir / "regulations" / regulation_id / f"{doc['versionLabel']}.md"
        if not path.exists():
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != doc["sha256"]:
            raise ValueError(
                f"업로드한 {doc['side']} 규정이 등록된 원문 {regulation_id}/{doc['versionLabel']}와 다릅니다"
            )


def create_app(
    runner=None,
    *,
    submit=None,
    spring_factory=SpringClient,
    regulation_id=REGULATION_ID,
    token=INTERNAL_TOKEN,
):
    runner = runner or build_runner()
    if submit is None:
        submit = ThreadPoolExecutor(max_workers=4, thread_name_prefix="agent-task").submit
    app = FastAPI(title="Rule Ripple Agent")

    def authorize(value):
        if value != token:
            raise HTTPException(401, "X-Internal-Token이 맞지 않습니다")

    def parse(model, body):
        try:
            req = model.model_validate(body)
        except ValidationError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not req.callback_base_url:
            raise HTTPException(400, "callbackBaseUrl이 필요합니다")
        return req

    def execute(req, work):
        spring = spring_factory(req.callback_base_url)
        bridge = SpringBridge(spring)
        try:
            bridge.finish(work(spring, bridge))
        except Exception as exc:
            bridge.fail(exc)
        finally:
            spring.close()

    @app.get("/health")
    def health():
        return {"status": "UP", "mode": AGENT_MODE}

    @app.post("/run", status_code=202)
    def run(body: dict, x_internal_token: str | None = Header(default=None)):
        authorize(x_internal_token)
        req = parse(RunRequest, body)

        def work(spring, bridge):
            check_documents(spring.documents(), regulation_id)
            return runner.start_backend(req, regulation_id=regulation_id, listener=bridge)

        submit(execute, req, work)
        return {"taskId": req.task_id, "accepted": True}

    @app.post("/resume", status_code=202)
    def resume(body: dict, x_internal_token: str | None = Header(default=None)):
        authorize(x_internal_token)
        req = parse(ResumeRequest, body)
        # 백엔드 확인(APPROVE + 승인 · 제외 목록)을 제안별 결정과 apply 승인으로 바꾼다.
        # 검토 대기 중이 아니면 409, 키가 현재 제안과 다르면 400. 그래프를 돌리기 전에 거부한다.
        try:
            decision = runner.backend_decision(req)
        except NotWaitingError as exc:
            raise HTTPException(409, str(exc)) from exc
        except DecisionError as exc:
            raise HTTPException(400, str(exc)) from exc
        # apply 노드는 이 요청의 콜백 주소로 큐 작업을 조회한다.
        submit(execute, req, lambda spring, bridge: runner.resume(
            req.thread_id, decision, task_id=req.task_id, step=req.step, listener=bridge, job_reader=spring.job))
        return {"taskId": req.task_id, "accepted": True}

    return app
