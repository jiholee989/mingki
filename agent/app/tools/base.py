"""노드별 접근 제한. mock과 실제 MCP가 같은 경계를 사용한다."""

from typing import Protocol

WRITE_TOOLS = frozenset({"create_draft_pr", "create_work_ticket"})


class Tools(Protocol):
    is_mock: bool

    def subset(self, *names: str) -> "ToolBelt": ...
    def describe(self, *names: str) -> list[dict]: ...


class ToolBelt:
    def __init__(self, source, names: frozenset[str]):
        self._source = source
        self.names = names

    @property
    def is_mock(self) -> bool:
        return self._source.is_mock

    def describe(self) -> list[dict]:
        return self._source.describe(*sorted(self.names))

    def __getattr__(self, name: str):
        if name not in self.names:
            raise PermissionError(f"이 노드에 허용되지 않은 도구: {name}")
        return getattr(self._source, name)
