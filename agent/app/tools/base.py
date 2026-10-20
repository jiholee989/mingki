"""노드마다 허용한 조회 도구만 사용할 수 있게 제한한다."""


class ToolBelt:
    def __init__(self, source, names: frozenset[str]):
        self._source = source
        self.names = names

    @property
    def is_local(self):
        return self._source.is_local

    def __getattr__(self, name):
        if name not in self.names:
            raise PermissionError(f"이 노드에 허용되지 않은 도구: {name}")
        return getattr(self._source, name)
