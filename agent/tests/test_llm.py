from types import SimpleNamespace

import pytest
from fastmcp.exceptions import ToolError
from langchain_core.messages import AIMessage
from app.llm import LlmReasoner
from app.patches import validate_diff
from app.reasoning import LocationsOutput, RequirementsOutput
from app.schemas import ChangeSpec, Requirement
from app.tools.mock import MockTools


def requirement():
    return Requirement(
        id="REQ-8",
        article_id="8",
        article="제8조",
        article_ref="reg://r/v4/8",
        change="modified",
        summary="이하에서 미만으로 변경",
        target="DSR_LIMIT",
    )


def spec(**updates):
    values = dict(
        id="S1",
        requirement_id="REQ-8",
        file="src/batch/limit_job.py",
        line=12,
        symbol="recalc_limits",
        snippet="if dsr > 0.4:",
        kind="code",
        is_target=True,
        reason="DSR 사용",
    )
    return ChangeSpec(**{**values, **updates})


class Model:
    def __init__(self, output, actions=()):
        self.output, self.actions, self.messages = output, iter(actions), []

    def with_structured_output(self, schema, **kwargs):
        return SimpleNamespace(invoke=lambda messages: self.output)

    def bind_tools(self, definitions):
        self.definitions = definitions
        return self

    def invoke(self, messages):
        self.messages.append(list(messages))
        return next(self.actions)


def test_llm_uses_selected_read_tool_and_observed_evidence():
    model = Model(
        LocationsOutput(items=[spec()]),
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "search_code", "args": {"query": "DSR_LIMIT"}, "id": "c1"}
                ],
            ),
            AIMessage(content="탐색 완료"),
        ],
    )
    reasoner = LlmReasoner(model)
    tools = MockTools()
    belt = tools.subset("search_code")
    rows = reasoner.locate(
        {
            "regulation_id": "r",
            "old_version": "v3",
            "new_version": "v4",
            "requirements": [requirement()],
        },
        belt,
    )
    assert rows[0].file == "src/batch/limit_job.py"
    assert tools.called("search_code") == [
        {"query": "DSR_LIMIT", "regex": False, "path_glob": "**/*"}
    ]
    assert model.messages[1][-1].type == "tool"
    assert {d["function"]["name"] for d in model.definitions} == {"search_code"}


def test_tool_error_is_returned_to_model():
    class Broken(MockTools):
        def search_code(self, query):
            raise ToolError("검색 조건을 바꾸세요")

    model = Model(
        LocationsOutput(items=[]),
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "search_code", "args": {"query": "x"}, "id": "c1"}
                ],
            ),
            AIMessage(content="근거 없음"),
        ],
    )
    LlmReasoner(model).locate(
        {
            "regulation_id": "r",
            "old_version": "v3",
            "new_version": "v4",
            "requirements": [],
        },
        Broken().subset("search_code"),
    )
    assert "검색 조건을 바꾸세요" in model.messages[1][-1].content


def test_unobserved_code_is_rejected():
    with pytest.raises(ValueError, match="도구 결과에 없는"):
        LlmReasoner._ground_locations([spec()], [])


def test_llm_output_can_represent_semantic_change_without_numeric_change():
    reasoner = LlmReasoner(Model(RequirementsOutput(items=[requirement()])))
    rows = reasoner.requirements({"old_text": "35% 이하", "new_text": "35% 미만"})
    assert len(rows) == 1 and rows[0].summary == "이하에서 미만으로 변경"


def test_model_cannot_call_write_tool():
    model = Model(
        None,
        [
            AIMessage(
                content="",
                tool_calls=[{"name": "create_draft_pr", "args": {}, "id": "bad"}],
            )
        ],
    )
    with pytest.raises(ValueError, match="권한"):
        LlmReasoner(model).locate(
            {
                "regulation_id": "r",
                "old_version": "v3",
                "new_version": "v4",
                "requirements": [],
            },
            MockTools().subset("search_code"),
        )


def test_model_turn_limit():
    calls = [
        AIMessage(
            content="",
            tool_calls=[{"name": "search_code", "args": {"query": "x"}, "id": str(i)}],
        )
        for i in range(2)
    ]
    with pytest.raises(ValueError, match="턴 한도"):
        LlmReasoner(Model(None, calls), max_turns=2).locate(
            {
                "regulation_id": "r",
                "old_version": "v3",
                "new_version": "v4",
                "requirements": [],
            },
            MockTools().subset("search_code"),
        )


@pytest.mark.parametrize(
    "diff",
    [
        "@@ other.py:12 @@\n-if dsr > 0.4:\n+if dsr > 0.35:",
        "@@ src/batch/limit_job.py:12 @@\n-if dsr > 0.4:\n+if dsr > 0.4:",
        "@@ src/batch/limit_job.py:12 @@\n-other code\n+if dsr > 0.35:",
        "",
    ],
)
def test_patch_cannot_change_unapproved_code_or_no_op(diff):
    with pytest.raises(ValueError):
        validate_diff(diff, [spec()])


def test_patch_allows_approved_location_only():
    validate_diff(
        "@@ src/batch/limit_job.py:12 @@\n-if dsr > 0.4:\n+if dsr > 0.35:", [spec()]
    )


def test_live_configuration_does_not_silently_fallback_to_demo(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    with pytest.raises(ValueError, match="OPENAI_MODEL"):
        LlmReasoner()


def test_local_sample_search_supports_snippet_and_regex():
    tools = MockTools()
    assert any(
        row["symbol"] == "senior_discount" for row in tools.search_code("age > 64")
    )
    assert any(
        row["symbol"] == "SENIOR_AGE_MONTHS"
        for row in tools.search_code(r"780|age\s*>\s*64", regex=True)
    )


def test_repeated_tool_limit_returns_error_without_executing_extra_call():
    model = Model(
        LocationsOutput(items=[]),
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "search_code", "args": {"query": "x"}, "id": str(i)}
                    for i in range(4)
                ],
            ),
            AIMessage(content="탐색 종료"),
        ],
    )
    tools = MockTools()
    LlmReasoner(model).locate(
        {
            "regulation_id": "r",
            "old_version": "v3",
            "new_version": "v4",
            "requirements": [],
        },
        tools.subset("search_code"),
    )
    assert len(tools.called("search_code")) == 3
    assert "한도" in model.messages[1][-1].content


def test_rule_grounding_uses_source_identity_and_canonical_value():
    item = spec(
        kind="product_rule",
        file="db/product_rules",
        symbol="R001 DSR_LIMIT",
        snippet="DSR_LIMIT = 0.4",
    )
    row = {
        "ruleId": "R001",
        "productId": "P001",
        "ruleKey": "DSR_LIMIT",
        "value": "0.40",
    }
    records = [
        {"tool": "get_product_rules", "args": {}, "result": [row]},
        {
            "tool": "get_product_rules",
            "args": {"rule_key": "DSR_LIMIT"},
            "result": [row],
        },
    ]
    LlmReasoner._ground_locations([item], records)
    assert (
        item.snippet == "DSR_LIMIT = 0.40"
        and item.line == 1
        and item.symbol == "R001 P001.DSR_LIMIT"
    )


def test_invalid_structured_response_has_bounded_format_retry():
    class InvalidModel:
        def __init__(self):
            self.calls = 0

        def with_structured_output(self, *args, **kwargs):
            return self

        def invoke(self, messages):
            self.calls += 1
            return {"items": [{"invalid": "shape"}]}

    model = InvalidModel()
    with pytest.raises(ValueError, match="LLM 출력 형식"):
        LlmReasoner(model).requirements({})
    assert model.calls == 2


def test_local_invalid_regex_is_a_recoverable_tool_error():
    with pytest.raises(ToolError, match="정규식"):
        MockTools().search_code("[", regex=True)
