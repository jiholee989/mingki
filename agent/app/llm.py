"""실제 LLM으로 법령 요건·상품 영향·변경 제안을 작성한다."""

import json
import logging
import os
import time
from pathlib import Path

from pydantic import ValidationError
from langchain_core.messages import HumanMessage, SystemMessage
from app.reasoning import BehaviorOutput, ProductAssessmentsOutput, RequirementsOutput
from app.schemas import Requirement, ProductDraft, ProductRevision, RevisionCheck, ProposalText, RevisionText, RuleChange
from app.validation import condition_errors, exemption_needs_customer_data, ground_conditions

logger = logging.getLogger(__name__)
PROMPTS = Path(__file__).resolve().parents[1] / "prompts"


def encode(value):
    return json.dumps(
        value, ensure_ascii=False, default=lambda v: v.model_dump(mode="json")
    )


def output_schema(model, payload=None):
    """API에서 필드 누락·잘못된 enum을 막고, 세부 검증은 Pydantic에서 한다."""
    schema = model.model_json_schema()
    def strict(node):
        if isinstance(node, dict):
            for key in ("default", "minimum", "maximum", "format"):
                node.pop(key, None)
            if "properties" in node:
                node["required"] = list(node["properties"])
                node["additionalProperties"] = False
            for value in node.values():
                strict(value)
        elif isinstance(node, list):
            for value in node:
                strict(value)
    strict(schema)
    if model is ProductAssessmentsOutput and payload:
        properties = schema["$defs"]["ProductAssessment"]["properties"]
        ids = sorted({r["ruleId"] for r in payload["rules"]})
        if ids:
            for name in ("target_rule_ids", "evidence_rule_ids"):
                properties[name]["items"]["enum"] = ids
        documents = sorted({d["uri"] for d in payload["documents"]})
        if documents:
            properties["document_refs"]["items"]["enum"] = documents
        sources = sorted({a["uri"] for a in payload["regulation_context"]} | set(documents))
        if sources:
            schema["$defs"]["ScopeCondition"]["properties"]["source_ref"]["enum"] = sources
    return schema


class LlmReasoner:
    def __init__(
        self, model=None, *, timeout=120, max_context_chars=60000
    ):
        if model is None:
            from langchain_openai import ChatOpenAI

            name = os.getenv("OPENAI_MODEL")
            if not name or not os.getenv("OPENAI_API_KEY"):
                raise ValueError(
                    "실제 LLM 모드에는 OPENAI_MODEL과 OPENAI_API_KEY가 필요합니다"
                )
            model = ChatOpenAI(model=name, timeout=timeout, max_retries=2)
        self.model = model
        self.max_context_chars = max_context_chars

    def _prompt(self, name):
        return (PROMPTS / "common.md").read_text() + "\n" + (PROMPTS / name).read_text()

    def _check_context(self, content):
        if len(content) > self.max_context_chars:
            raise ValueError(
                "모델 문맥 한도 초과: 요건·상품을 더 작은 작업으로 나누세요"
            )

    def _ask(self, prompt, schema, payload):
        content = encode(payload)
        self._check_context(content)
        started = time.monotonic()
        logger.info("요청 stage=%s", prompt)
        messages = [
            SystemMessage(content=self._prompt(prompt)),
            HumanMessage(content=content),
        ]
        for attempt in range(2):
            try:
                output = self.model.with_structured_output(
                    output_schema(schema, payload), method="json_schema", strict=True
                ).invoke(messages)
                output = schema.model_validate(output)
                break
            except ValidationError as exc:
                logger.warning("출력 형식 재확인 stage=%s: %s", prompt, "; ".join(f"{e['loc']}: {e['msg']}" for e in exc.errors(include_input=False)[:3]))
                if attempt:
                    raise ValueError(f"LLM 출력 형식 오류: {prompt}") from None
                messages.append(
                    HumanMessage(
                        content="출력 형식을 지켜 다시 작성하세요: "
                        + str(exc.errors(include_input=False))
                    )
                )
        logger.info("model stage=%s elapsed=%.2f", prompt, time.monotonic() - started)
        return output

    def requirements(self, diff):
        changes = diff.get("changes", [])
        body = [c for c in changes if not c["article_id"].startswith("supp-")]
        payload = {**diff, "changes": body,
                   "supplementary_changes": [c for c in changes if c not in body]}
        expected = {c["article_id"] for c in body}
        for attempt in range(2):
            candidates = self._ask("requirement.md", RequirementsOutput, payload).items
            missing = expected - {c.article_id for c in candidates}
            if not missing:
                break
            if attempt:
                raise ValueError(f"변경 조항의 실질 변경 판단이 빠졌습니다: {sorted(missing)}")
            payload["correction"] = f"누락 조항 {sorted(missing)}도 반드시 판정하세요. 제N조의2는 본문 조항이며 부칙이 아닙니다."

        # 문체 판정도 출력에 남기되, 실질 변화와 동작 차이를 설명한 요건만 진행한다.
        items = [
            Requirement.model_validate(item.model_dump())
            for item in candidates
            if item.is_material and not item.article_id.startswith("supp-")
        ]
        sources = {c["article_id"]: c for c in body}
        for item in items:
            if item.behavior_change.strip():
                continue
            source = sources.get(item.article_id, {})
            logger.info("동작 설명 보완 article=%s", item.article_id)
            try:
                detail = self._ask("requirement-detail.md", BehaviorOutput,
                                   {"requirement": item, "source": source})
                item.behavior_change = detail.behavior_change.strip()
            except ValueError:
                pass  # 형식 보완 실패 시에도 실제 원문을 보존해 제안 검토로 넘긴다.
            if not item.behavior_change:
                item.behavior_change = (
                    f"기존 원문: {source.get('old_text') or '없음'} / "
                    f"개정 원문: {source.get('new_text') or '없음'}"
                    " (동작 영향 설명 미생성: 제안 검토에서 확인 필요)"
                )
                item.summary += " [동작 영향 확인 필요]"
                logger.warning("동작 설명 미생성 article=%s: 원문과 함께 검토 필요로 표시", item.article_id)
        logger.info("요건 선별: 채택 %s / 제외 %s", len(items), len(candidates) - len(items))
        return items

    def product_impacts(self, requirements, products, rules, regulation_context=None, documents=None, data_gaps=None):
        items = []
        # 모든 상품을 빠짐없이 다루되 한 번의 모델 입력은 작게 유지한다.
        for req in requirements:
            for offset in range(0, len(products), 4):
                batch = products[offset:offset + 4]
                ids = {p["productId"] for p in batch}
                payload = {"requirement": req, "products": batch,
                           "rules": [row for row in rules if row["productId"] in ids],
                           "documents": [doc for doc in documents or [] if doc["productId"] in ids],
                           "regulation_context": regulation_context or [], "data_gaps": data_gaps or []}
                for attempt in range(2):
                    rows = self._ask("product-impacts.md", ProductAssessmentsOutput, payload).items
                    errors = []
                    for pid in ids:
                        matched = [row for row in rows if row.product_id == pid and row.requirement_id == req.id]
                        if len(matched) != 1:
                            errors.append(f"{pid}: 정확히 한 번 판단해야 합니다")
                    for row in rows:
                        known_rules = {r["ruleId"] for r in payload["rules"] if r["productId"] == row.product_id}
                        known_docs = {d["uri"] for d in payload["documents"] if d["productId"] == row.product_id}
                        if row.product_id not in ids or row.requirement_id != req.id:
                            errors.append("요청 범위 밖의 상품·요건이 있습니다")
                        if not set(row.target_rule_ids + row.evidence_rule_ids) <= known_rules or not set(row.document_refs) <= known_docs:
                            bad_rules = sorted(set(row.target_rule_ids + row.evidence_rule_ids) - known_rules)
                            bad_docs = sorted(set(row.document_refs) - known_docs)
                            errors.append(f"{row.product_id}: 미조회 규칙 {bad_rules}·문서 {bad_docs}를 제거하세요. 변경 대상만 target_rule_ids, 참조 근거만 evidence_rule_ids에 넣고 목록 전체를 복사하지 마세요")
                        sources = {a["uri"]: a["text"] for a in regulation_context or []}
                        sources.update({d["uri"]: d["content"] for d in payload["documents"] if d["productId"] == row.product_id})
                        ground_conditions(row, sources)
                        errors.extend(condition_errors(row, sources))
                        own_rules = [r for r in payload["rules"] if r["productId"] == row.product_id]
                        if row.applicability == "excluded" and exemption_needs_customer_data(req, own_rules):
                            errors.append(f"{row.product_id}: 수치로 정한 DSR 예외 한도는 차주별 조건입니다. 차주 자료 없이 상품 전체를 제외하지 말고 needs_review/unknown 또는 조건부 범위로 설명하세요")
                    if not errors:
                        break
                    logger.warning("상품 영향 근거 보완: %s", errors)
                    if not attempt:
                        payload["previous_assessments"] = rows
                        payload["correction"] = errors
                items.extend(rows)
        return items

    def draft_product(self, context):
        # 조회 원문에서 계산된 필수 값은 모델에게 다시 생성시키지 않는다.
        changes = [RuleChange(**c) for c in context.get("mandatory_changes", []) if c["proposed_value"] is not None]
        if context.get("previous_proposal") and context.get("comment", "").strip():
            text = self._ask("product-revision.md", RevisionText, context)
            if not text.revision_response.strip():
                raise ValueError("수정 의견의 반영 설명이 없습니다")
            return ProductRevision(**text.model_dump(), changes=changes)
        text = self._ask("product-proposal.md", ProposalText, context)
        return ProductDraft(**text.model_dump(), changes=changes)

    def check_revision(self, context):
        return self._ask("revision-check.md", RevisionCheck, context)
