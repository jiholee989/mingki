"""Spring `/internal/**` 콜백 클라이언트. 계약은 docs/BACKEND_API.md 6 · 7절."""

import os
import time

import httpx

INTERNAL_TOKEN = os.getenv("INTERNAL_TOKEN", "rr-internal-dev-token")


class SpringError(RuntimeError):
    """Spring이 콜백을 거부했다. 상태 충돌(409)이면 작업 순서가 계약과 다르다는 뜻이다."""


class SpringClient:
    def __init__(self, callback_base_url: str, *, token=INTERNAL_TOKEN, transport=None, retries=2, backoff=0.5):
        # callbackBaseUrl = {backend}/internal/tasks/{taskId}
        self.task_url = callback_base_url.rstrip("/")
        self.internal_url = self.task_url.rsplit("/tasks/", 1)[0]
        self.retries = retries
        self.backoff = backoff
        self._http = httpx.Client(
            headers={"X-Internal-Token": token, "X-Internal-Caller": "agent"},
            timeout=10,
            transport=transport,
        )

    def close(self):
        self._http.close()

    def _call(self, method, url, body=None):
        """연결 실패 · 시간 초과 · 5xx 는 짧게 다시 시도한다. 4xx 는 요청이 틀린 것이라 바로 실패한다.

        LLM 작업이 몇 분씩 도는 동안 콜백 한 번이 흔들렸다고 작업 전체를 FAILED 로 끝내지 않기 위해서다.
        """
        for attempt in range(self.retries + 1):
            try:
                res = self._http.request(method, url, json=body)
            except httpx.TransportError as exc:
                if attempt == self.retries:
                    raise SpringError(f"{method} {url} → 연결 실패: {exc}") from exc
            else:
                if not res.is_error:
                    return res.json() if res.content else None
                if res.status_code < 500 or attempt == self.retries:
                    raise SpringError(f"{method} {url} → {res.status_code}: {res.text[:300]}")
            time.sleep(self.backoff * (attempt + 1))

    def documents(self):
        return self._call("GET", f"{self.task_url}/documents")

    def event(self, type_, payload=None):
        self._call("POST", f"{self.task_url}/events", {"type": type_, "payload": payload or {}})

    def put(self, path, body):
        self._call("PUT", f"{self.task_url}/{path}", body)

    def post(self, path, body):
        self._call("POST", f"{self.task_url}/{path}", body)

    def job(self, job_id):
        return self._call("GET", f"{self.internal_url}/jobs/{job_id}")
