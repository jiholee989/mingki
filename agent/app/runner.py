"""CLI와 향후 FastAPI가 공유할 실행기. HTTP·업무 DB는 이 모듈 밖에 둔다."""

from threading import Lock
from langgraph.types import Command
from app.backend import ResumeRequest, RunRequest
from app.nodes.review import validate_review


class DecisionError(ValueError):
    """그래프 실행 전에 거부된 결정. 사용자가 다시 입력할 수 있다."""


class AgentRunner:
    def __init__(self, graph, on_update=None):
        self.graph = graph
        self._lock = Lock()
        self.on_update = on_update

    @staticmethod
    def config(thread_id):
        return {"configurable": {"thread_id": thread_id}, "recursion_limit": 100}

    def start(
        self,
        task_id,
        regulation_id,
        old_version="v3",
        new_version="v4",
        *,
        thread_id=None,
        article_ids=None,
    ):
        thread_id = thread_id or task_id
        config = self.config(thread_id)
        # 같은 프로세스의 중복 실행/재개를 직렬화한다. 분산 배포에는 외부 잠금이 필요하다.
        with self._lock:
            if self.graph.get_state(config).values:
                raise ValueError(
                    "이미 시작한 thread_id입니다. 승인 재개는 resume을 사용하세요"
                )
            return self._invoke(
                {
                    "task_id": task_id,
                    "regulation_id": regulation_id,
                    "old_version": old_version,
                    "new_version": new_version,
                    "article_ids": article_ids or [],
                },
                config,
            )

    def resume(self, thread_id, decision, *, task_id=None, step=None):
        config = self.config(thread_id)
        with self._lock:
            snapshot = self.graph.get_state(config)
            interrupts = [i for task in snapshot.tasks for i in task.interrupts]
            if not interrupts:
                raise DecisionError("승인을 기다리는 작업이 없습니다")
            if task_id and snapshot.values["task_id"] != task_id:
                raise DecisionError("다른 작업의 재개 요청입니다")
            expected = "REVIEW"
            if step and step != expected:
                raise DecisionError("현재는 상품별 제안 검토 단계입니다. 중간 요건 승인은 사용하지 않습니다")
            validator = validate_review
            try:
                validator(snapshot.values, decision)
            except ValueError as exc:
                raise DecisionError(str(exc)) from exc
            return self._invoke(Command(resume=decision), config)

    def _invoke(self, value, config):
        if self.on_update is None:
            return self.graph.invoke(value, config)
        interrupts = ()
        for update in self.graph.stream(value, config, stream_mode="updates"):
            for node, delta in update.items():
                if node == "__interrupt__":
                    interrupts = delta
                else:
                    self.on_update(node, delta)
        out = dict(self.graph.get_state(config).values)
        if interrupts:
            out["__interrupt__"] = interrupts
        return out

    def resume_backend(self, request: ResumeRequest):
        return self.resume(
            request.thread_id,
            request.to_decision(),
            task_id=request.task_id,
            step=request.step,
        )

    def start_backend(self, request: RunRequest, *, regulation_id):
        return self.start(**request.to_input(regulation_id))
