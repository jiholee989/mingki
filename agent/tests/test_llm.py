from types import SimpleNamespace
import pytest
from app.llm import LlmReasoner, output_schema
from app.reasoning import RequirementCandidate, RequirementsOutput
from app.schemas import Requirement, ProductDraft


class Model:
    def __init__(self, output):
        self.output = output

    def with_structured_output(self, schema, **kwargs):
        return SimpleNamespace(invoke=lambda messages: self.output)


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

def test_llm_output_can_represent_semantic_change_without_numeric_change():
    reasoner = LlmReasoner(Model(RequirementsOutput(items=[RequirementCandidate(**{**requirement().model_dump(), "behavior_change": "기존에는 35% 허용 / 개정 후에는 35% 거절"}, is_material=True)])))
    rows = reasoner.requirements({"old_text": "35% 이하", "new_text": "35% 미만"})
    assert len(rows) == 1 and rows[0].summary == "이하에서 미만으로 변경"

def test_missing_description_preserves_source_and_marks_review_needed():
    output = {"items": [{**requirement().model_dump(), "is_material": True}]}
    rows = LlmReasoner(Model(output)).requirements({"changes": [{
        "article_id": "8", "old_text": "35% 이하", "new_text": "35% 미만",
    }]})
    assert len(rows) == 1
    assert "35% 이하" in rows[0].behavior_change
    assert "35% 미만" in rows[0].behavior_change
    assert "확인 필요" in rows[0].summary

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

def test_product_assessment_and_proposal_use_structured_model_without_tool_loop():
    import json
    from app.schemas import ProductDraft

    class ProductModel:
        def __init__(self):
            self.requests = []

        def with_structured_output(self, schema, **kwargs):
            assert kwargs == {"method": "json_schema", "strict": True}
            assert schema["additionalProperties"] is False
            def invoke(messages):
                self.requests.append(messages)
                if schema["title"] == "ProductAssessmentsOutput":
                    return {"items": [{"requirement_id": "REQ-8", "product_id": "P001", "impact": "change_required", "evidence_rule_ids": ["R001"], "reason": "현재 상한 40%, 개정 상한 35%"}]}
                return {"recommendation": "DSR 상한을 35%로 변경", "actions": ["신규 신청의 상한 변경"], "precautions": ["기존 신청 경과조치 확인"], "revision_response": "요청대로 기존 신청 경과조치를 구분했습니다"}
            return SimpleNamespace(invoke=invoke)

    model = ProductModel()
    reasoner = LlmReasoner(model)
    rows = reasoner.product_impacts([requirement()], [{"productId": "P001"}], [{"ruleId": "R001", "productId": "P001"}])
    assert rows[0].product_id == "P001"
    context = {"previous_proposal": {"version": 1}, "comment": "경과조치 구분"}
    draft = reasoner.draft_product(context)
    assert isinstance(draft, ProductDraft)
    assert "경과조치" in draft.revision_response
    assert json.loads(model.requests[-1][1].content) == context
    assert "상품" in model.requests[-1][0].content
    assert len(model.requests) == 2


@pytest.mark.parametrize("schema", [RequirementsOutput, ProductDraft])
def test_structured_schema_requires_every_field(schema):
    result = output_schema(schema)
    assert result["additionalProperties"] is False
    assert result["required"] == list(result["properties"])


def test_missing_api_key_never_falls_back_to_fixed_answers(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("OPENAI_MODEL", "configured-model")
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        LlmReasoner()


def test_missing_changed_article_is_not_silently_dropped():
    reasoner = LlmReasoner(Model({"items": []}))
    with pytest.raises(ValueError, match="빠졌습니다"):
        reasoner.requirements({"changes": [{"article_id": "15-2"}]})


def test_invalid_output_retries_once_then_stops():
    class InvalidModel:
        def __init__(self):
            self.calls = 0
        def with_structured_output(self, schema, **kwargs):
            def invoke(messages):
                self.calls += 1
                return {"actions": "invalid list"}
            return SimpleNamespace(invoke=invoke)
    model = InvalidModel()
    with pytest.raises(ValueError, match="출력 형식"):
        LlmReasoner(model).draft_product({})
    assert model.calls == 2


def test_context_limit_stops_before_model_call():
    with pytest.raises(ValueError, match="문맥 한도"):
        LlmReasoner(Model(None), max_context_chars=10).draft_product({"too_large": "x" * 100})


def test_wording_only_change_is_excluded():
    candidate = RequirementCandidate(**{**requirement().model_dump(), "behavior_change": ""}, is_material=False)
    assert LlmReasoner(Model(RequirementsOutput(items=[candidate]))).requirements({}) == []


def test_revision_uses_dedicated_prompt_and_requires_feedback_explanation():
    import json
    class RevisionModel:
        def __init__(self):
            self.messages = None
        def with_structured_output(self, schema, **kwargs):
            assert schema["title"] == "RevisionText"
            def invoke(messages):
                self.messages = messages
                return {"recommendation": "DSR 변경", "actions": ["기존 신청 제외"], "precautions": [], "revision_response": "기존 신청 제외 조건을 수행 항목에 추가했습니다"}
            return SimpleNamespace(invoke=invoke)
    model = RevisionModel()
    draft = LlmReasoner(model).draft_product({"previous_proposal": {"recommendation": "기존"}, "comment": "기존 신청 제외"})
    assert "기존 신청 제외" in json.loads(model.messages[1].content)["comment"]
    assert "사용자의 comment" in model.messages[0].content
    assert "수행 항목" in draft.revision_response


def test_revision_without_explanation_is_not_accepted():
    model = Model({"recommendation": "변경", "actions": ["변경"], "precautions": [], "revision_response": " "})
    with pytest.raises(ValueError, match="반영 설명"):
        LlmReasoner(model).draft_product({"previous_proposal": {"version": 1}, "comment": "요청"})


def test_expanded_products_are_batched_without_omissions_or_cross_product_documents():
    import json
    seen = []
    class BatchModel:
        def with_structured_output(self, schema, **kwargs):
            def invoke(messages):
                payload = json.loads(messages[1].content)
                seen.append(payload)
                ids = {p["productId"] for p in payload["products"]}
                assert len(ids) <= 4
                assert all(r["productId"] in ids for r in payload["rules"])
                assert all(d["productId"] in ids for d in payload["documents"])
                return {"items": [{"requirement_id": payload["requirement"]["id"], "product_id": p["productId"],
                                   "impact": "needs_review", "evidence_rule_ids": [], "document_refs": [], "reason": "자료 확인"}
                                  for p in payload["products"]]}
            return SimpleNamespace(invoke=invoke)
    from app.tools.local import LocalTools
    tools = LocalTools()
    products = tools.get_products()
    LlmReasoner(BatchModel()).product_impacts([requirement()], products, tools.get_product_rules(),
        documents=tools.get_product_documents([p["productId"] for p in products])["documents"])
    assert len(seen) == 3
    assert [p["productId"] for batch in seen for p in batch["products"]] == [p["productId"] for p in products]


def test_product_evidence_ids_are_repaired_once_before_final_grounding():
    import json
    requests = []
    class Repair:
        def with_structured_output(self, schema, **kwargs):
            def invoke(messages):
                payload = json.loads(messages[1].content)
                requests.append(payload)
                return {"items": [{"requirement_id": "REQ-8", "product_id": "P001", "impact": "no_change",
                                   "reason": "유지", "document_refs": [],
                                   "evidence_rule_ids": ["R001"] if payload.get("correction") else ["DSR_LIMIT"]}]}
            return SimpleNamespace(invoke=invoke)
    rows = LlmReasoner(Repair()).product_impacts([requirement()], [{"productId": "P001"}], [{"productId": "P001", "ruleId": "R001"}])
    assert len(requests) == 2 and requests[-1]["correction"]
    assert rows[0].evidence_rule_ids == ["R001"]


def test_impact_schema_separates_rule_ids_from_source_uris():
    from app.reasoning import ProductAssessmentsOutput
    payload = {"rules": [{"ruleId": "R001"}], "documents": [{"uri": "product-doc://P001"}],
               "regulation_context": [{"uri": "reg://r/v4/8"}]}
    schema = output_schema(ProductAssessmentsOutput, payload)
    props = schema["$defs"]["ProductAssessment"]["properties"]
    assert props["evidence_rule_ids"]["items"]["enum"] == ["R001"]
    assert props["document_refs"]["items"]["enum"] == ["product-doc://P001"]


def test_model_text_cannot_override_source_owned_mandatory_values():
    model = Model({"recommendation": "제안", "actions": ["필수 변경"], "precautions": [],
                   "changes": [{"rule_id": "fake", "proposed_value": "999"}]})
    contract = [{"rule_id": "R001", "rule_key": "DSR_LIMIT", "current_value": "0.40", "proposed_value": "0.35", "unit": "ratio"}]
    draft = LlmReasoner(model).draft_product({"mandatory_changes": contract})
    assert [c.model_dump() for c in draft.changes] == contract
