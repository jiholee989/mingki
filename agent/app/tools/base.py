"""노드마다 허용한 조회 도구만 사용할 수 있게 제한하고, 호출을 작업 기록에 남긴다."""

import time


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


class Recorded:
    """도구 호출 전후를 recorder(작업 기록)에 알린다. 결과와 예외는 그대로 돌려준다. 권한 검사는 ToolBelt가 한다."""

    def __init__(self, tools, recorder, node):
        self._tools, self._recorder, self._node = tools, recorder, node

    @property
    def is_local(self):
        return self._tools.is_local

    def __getattr__(self, name):
        target = getattr(self._tools, name)
        if not callable(target):
            return target

        def call(*args, **kwargs):
            self._recorder.tool_started(self._node, name, brief_args(args, kwargs))
            started = time.monotonic()
            try:
                result = target(*args, **kwargs)
            except Exception as exc:
                self._recorder.tool_finished(self._node, name, ok=False, ms=_ms(started), error=str(exc)[:200])
                raise
            self._recorder.tool_finished(self._node, name, ok=True, ms=_ms(started), summary=summarize(result))
            return result

        return call


def recorder_of(config):
    """실행 config로 받은 작업 기록 대상 (runner가 호출마다 넣는다). 없으면 None."""
    return (config or {}).get("configurable", {}).get("recorder")


def recording(tools, recorder, node):
    """recorder가 있으면 도구 호출을 기록하고, 없으면 도구를 그대로 쓴다."""
    return Recorded(tools, recorder, node) if hasattr(recorder, "tool_started") else tools


def _ms(started):
    return round((time.monotonic() - started) * 1000)


def _brief(value):
    if isinstance(value, (list, tuple, set)):
        return f"{len(value)}개"
    if isinstance(value, str) and len(value) > 80:
        return value[:80] + "…"
    return value


def brief_args(args, kwargs):
    """기록용 인자. ID 목록 같은 긴 값은 개수로 줄인다."""
    out = {k: _brief(v) for k, v in kwargs.items() if v is not None}
    if args:
        out["args"] = [_brief(a) for a in args]
    return out


def summarize(result):
    """기록용 결과 요약: 목록은 건수, 목록을 담은 dict는 키별 건수, 그 밖은 짧은 값 몇 개."""
    if isinstance(result, list):
        return f"{len(result)}건"
    if isinstance(result, dict):
        lists = [f"{k} {len(v)}건" for k, v in result.items() if isinstance(v, list)]
        if lists:
            return ", ".join(lists)
        scalars = [f"{k}={v}" for k, v in result.items() if isinstance(v, (str, int, float, bool)) and len(str(v)) <= 40]
        return ", ".join(scalars[:3]) or None
    return None
