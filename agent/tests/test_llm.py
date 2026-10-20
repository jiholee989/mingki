from types import SimpleNamespace

import pytest
from fastmcp.exceptions import ToolError
from langchain_core.messages import AIMessage
from app.llm import LlmReasoner
from app.patches import validate_diff
from app.reasoning import LocationsOutput, RequirementCandidate, RequirementsOutput, TestsOutput as GeneratedTestsOutput
from app.schemas import ChangeSpec, Requirement, TestCase
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
        before="DSR 0.40 초과 거절",
        after="DSR 0.35 초과 거절",
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


def test_unobserved_code_is_deferred_and_cannot_be_patched():
    item = spec()
    LlmReasoner._ground_locations([item], [])
    assert item.needs_review and not item.is_target
    assert item.line == 0 and item.snippet == ""


def test_llm_output_can_represent_semantic_change_without_numeric_change():
    reasoner = LlmReasoner(Model(RequirementsOutput(items=[RequirementCandidate(**{**requirement().model_dump(), "behavior_change": "기존에는 35% 허용 / 개정 후에는 35% 거절"}, is_material=True)])))
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


def test_non_material_candidate_is_excluded_but_behavior_change_is_kept():
    wording = RequirementCandidate(**{
        **requirement().model_dump(), "id": "REQ-6", "article_id": "6",
        "summary": "확인하여야 한다 → 확인해야 한다", "behavior_change": "",
    }, is_material=False)
    actual = RequirementCandidate(**{
        **requirement().model_dump(), "behavior_change": "기존에는 경계값 허용 / 개정 후에는 거절",
    }, is_material=True)
    rows = LlmReasoner(Model(RequirementsOutput(items=[wording, actual]))).requirements({})
    assert [r.id for r in rows] == ["REQ-8"]
    assert rows[0].behavior_change


def test_missing_description_preserves_source_and_marks_review_needed():
    output = {"items": [{**requirement().model_dump(), "is_material": True}]}
    rows = LlmReasoner(Model(output)).requirements({"changes": [{
        "article_id": "8", "old_text": "35% 이하", "new_text": "35% 미만",
    }]})
    assert len(rows) == 1
    assert "35% 이하" in rows[0].behavior_change
    assert "35% 미만" in rows[0].behavior_change
    assert "확인 필요" in rows[0].summary


def test_missing_file_context_is_deferred_instead_of_becoming_a_patch_target():
    item = spec()
    records = [{"tool": "search_code", "args": {}, "result": [item.model_dump()]}]
    LlmReasoner._ground_locations([item], records)
    assert item.needs_review and not item.is_target
    assert "본문 미조회" in item.reason


def test_observed_file_context_allows_target_with_specific_change():
    item = spec(line=2)
    records = [{"tool": "get_file", "args": {"path": item.file}, "result": "def check(dsr):\n    if dsr > 0.4:\n        return False\n"}]
    LlmReasoner._ground_locations([item], records)
    assert item.is_target and not item.needs_review


def test_uncertain_or_vague_candidate_is_never_a_patch_target():
    for item in [spec(needs_review=True), spec(after="")]:
        records = [{"tool": "search_code", "args": {}, "result": [item.model_dump()]}]
        LlmReasoner._ground_locations([item], records)
        assert item.needs_review and not item.is_target


def test_model_cannot_finish_with_only_business_rule_lookup():
    model = Model(LocationsOutput(items=[]), [
        AIMessage(content="상품 규칙만 조사하고 종료"),
        AIMessage(content="", tool_calls=[{"name": "search_code", "args": {"query": "DSR"}, "id": "code"}]),
        AIMessage(content="관련 후보 조사 완료"),
    ])
    tools = MockTools()
    LlmReasoner(model).locate({"regulation_id": "r", "old_version": "v3", "new_version": "v4", "requirements": [requirement()]}, tools.subset("search_code"))
    assert "코드 검색이 아직 없습니다" in model.messages[1][-1].content
    assert len(tools.called("search_code")) == 1


def test_rule_without_product_description_is_deferred():
    item = spec(kind="product_rule", file="db/product_rules", symbol="R001 P001.DSR_LIMIT")
    record = {"tool": "get_product_rules", "args": {}, "result": [{
        "ruleId": "R001", "productId": "P001", "ruleKey": "DSR_LIMIT", "value": "0.40",
    }]}
    LlmReasoner._ground_locations([item], [record])
    assert item.needs_review and not item.is_target
    assert "상품 설명 미조회" in item.reason


def test_search_results_are_supplemented_with_file_context():
    model = Model(LocationsOutput(items=[spec()]), [
        AIMessage(content="", tool_calls=[{"name": "search_code", "args": {"query": "DSR_LIMIT"}, "id": "s"}]),
        AIMessage(content="조사 종료"),
    ])
    tools = MockTools()
    rows = LlmReasoner(model).locate({"regulation_id": "r", "old_version": "v3", "new_version": "v4", "requirements": [requirement()]}, tools.subset("search_code", "get_file"))
    assert tools.called("get_file")
    assert rows[0].is_target and not rows[0].needs_review


def test_only_empty_new_obligation_description_is_repaired():
    bad = {**requirement().model_dump(), "change": "added", "article_id": "15-2", "is_material": True}
    class RepairModel:
        def __init__(self):
            self.titles = []
        def with_structured_output(self, schema, **kwargs):
            self.titles.append(schema["title"])
            output = {"behavior_change": "기존에는 의무 없음 / 개정 후 확인 의무 추가"} if schema["title"] == "BehaviorOutput" else {"items": [bad]}
            return SimpleNamespace(invoke=lambda messages: output)
    model = RepairModel()
    rows = LlmReasoner(model).requirements({"changes": [{"article_id": "15-2"}]})
    assert len(rows) == 1 and rows[0].article_id == "15-2"
    assert "의무 추가" in rows[0].behavior_change
    assert model.titles == ["RequirementsOutput", "BehaviorOutput"]


def test_supplementary_empty_description_does_not_trigger_repair():
    body = {**requirement().model_dump(), "is_material": True, "behavior_change": "기존에는 이하 / 개정 후 미만"}
    supplement = {**body, "id": "REQ-supp-2", "article_id": "supp-2", "behavior_change": ""}
    rows = LlmReasoner(Model({"items": [body, supplement]})).requirements({"changes": [{"article_id": "8"}, {"article_id": "supp-2"}]})
    assert [r.id for r in rows] == ["REQ-8"]


def test_tests_that_only_compare_local_values_are_rejected():
    test = TestCase(id="T1", requirement_id="REQ-8", kind="boundary", description="fake", inputs="{}", expected="35%", code="def test_fake():\n    value = 0.35\n    assert value == 0.35\n")
    reasoner = LlmReasoner(Model(GeneratedTestsOutput(items=[test])))
    cases = reasoner.tests({"requirements": [requirement()], "change_specs": [spec()]}, MockTools().subset("get_file"))
    assert cases[0].code is None
    assert "실제 코드 검증 필요" in cases[0].description


def test_output_schema_requires_all_fields_and_keeps_target_enum():
    from app.llm import output_schema
    schema = output_schema(LocationsOutput)
    item = schema["$defs"]["ChangeSpec"]
    assert set(item["required"]) == set(item["properties"])
    assert item["additionalProperties"] is False
    assert "default" not in item["properties"]["needs_review"]
    assert "product_rule" in item["properties"]["kind"]["enum"]


def test_unknown_function_keyword_is_deferred_before_test_freeze():
    test = TestCase(id="bad-keyword", requirement_id="REQ-8", kind="boundary", description="wrong API", inputs="{}", expected="reject", code="from src.loan.eligibility import is_eligible\ndef test_dsr():\n    assert is_eligible(40, dsr=0.36)\n")
    reasoner = LlmReasoner(Model(GeneratedTestsOutput(items=[test])))
    items = reasoner._tests_for_requirement({"requirements": [requirement()], "change_specs": [], "files": {"src/loan/eligibility.py": "def is_eligible(age, credit_score):\n    return age >= 19 and credit_score >= 600\n"}})
    assert items[0].code is None


def test_wrong_line_is_corrected_only_from_unique_observed_source():
    item = spec(file="src/loan/rate.py", line=6, symbol="senior_discount", snippet="if age > 64:")
    content = "def senior_discount(age):\n    if age > 64:\n        return 0.003\n"
    LlmReasoner._ground_locations([item], [{"tool": "get_file", "args": {"path": item.file}, "result": content}])
    assert item.line == 2 and item.is_target


def test_ambiguous_wrong_line_is_deferred_without_stopping_other_candidates():
    bad = spec(line=99)
    good = spec(id="S2", line=2)
    content = "def first(dsr):\n    if dsr > 0.4:\n        return False\ndef second(dsr):\n    if dsr > 0.4:\n        return True\n"
    records = [{"tool": "get_file", "args": {"path": bad.file}, "result": content}]
    LlmReasoner._ground_locations([bad, good], records)
    assert bad.needs_review and not bad.is_target and bad.line == 0
    assert good.is_target and good.line == 2


def test_empty_snippet_does_not_match_blank_source_line():
    item = spec(line=2, snippet="")
    LlmReasoner._ground_locations([item], [{"tool": "get_file", "args": {"path": item.file}, "result": "x = 1\n\ny = 2\n"}])
    assert item.needs_review and not item.is_target


def test_unobserved_rule_is_deferred_not_accepted_as_target():
    item = spec(kind="product_rule", file="db/product_rules", symbol="R999 P001.OTHER")
    LlmReasoner._ground_locations([item], [])
    assert item.needs_review and not item.is_target and not item.snippet
