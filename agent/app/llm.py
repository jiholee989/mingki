"""LLM 판단과 제한된 읽기 도구 루프. 외부 쓰기는 이 모듈에 제공하지 않는다."""

import ast
import json
import logging
import os
import re
import time
from pathlib import Path

from fastmcp.exceptions import ToolError
from pydantic import ValidationError
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from app.reasoning import BehaviorOutput, Draft, LocationsOutput, RequirementsOutput, TestsOutput
from app.schemas import Requirement

logger = logging.getLogger(__name__)
PROMPTS = Path(__file__).resolve().parents[1] / "prompts"


def encode(value):
    return json.dumps(
        value, ensure_ascii=False, default=lambda v: v.model_dump(mode="json")
    )


def output_schema(model):
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
    return schema


class LlmReasoner:
    is_demo = False

    def __init__(
        self, model=None, *, max_turns=8, timeout=120, max_context_chars=60000
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
        self.max_turns = max_turns
        self.timeout = timeout
        self.max_context_chars = max_context_chars

    def _prompt(self, name):
        return (PROMPTS / "common.md").read_text() + "\n" + (PROMPTS / name).read_text()

    def _check_context(self, content):
        if len(content) > self.max_context_chars:
            raise ValueError(
                "모델 문맥 한도 초과: 요건·파일을 더 작은 작업으로 나누세요"
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
                    output_schema(schema), method="json_schema", strict=True
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
                pass  # 형식 보완 실패 시에도 실제 원문을 보존해 첫 검토로 넘긴다.
            if not item.behavior_change:
                item.behavior_change = (
                    f"기존 원문: {source.get('old_text') or '없음'} / "
                    f"개정 원문: {source.get('new_text') or '없음'}"
                    " (동작 영향 설명 미생성: 첫 검토에서 확인 필요)"
                )
                item.summary += " [동작 영향 확인 필요]"
                logger.warning("동작 설명 미생성 article=%s: 원문과 함께 검토 필요로 표시", item.article_id)
        logger.info("요건 선별: 채택 %s / 제외 %s", len(items), len(candidates) - len(items))
        return items

    def locate(self, state, tools):
        payload = {
            k: state[k]
            for k in ("regulation_id", "old_version", "new_version", "requirements")
        }
        messages = [
            SystemMessage(content=self._prompt("locate.md")),
            HumanMessage(content=encode(payload)),
        ]
        model = self.model.bind_tools(tools.describe())
        started, counts, records = time.monotonic(), {}, []
        for turn in range(self.max_turns):
            if time.monotonic() - started >= self.timeout:
                raise TimeoutError("영향 탐색 제한 시간 초과")
            self._check_context(encode([m.content for m in messages]))
            response = model.invoke(messages)
            messages.append(response)
            logger.info("locate turn=%s usage=%s", turn + 1, response.usage_metadata)
            if not response.tool_calls:
                if payload["requirements"] and "search_code" in tools.names and not any(
                    r["tool"] == "search_code" for r in records
                ):
                    messages.append(HumanMessage(content=
                        "코드 검색이 아직 없습니다. search_code로 정책 키·종전 값·조건을 조사한 뒤 "
                        "후보 파일을 get_file로 확인하세요. 관련 코드가 없다는 결과도 근거로 남기세요."
                    ))
                    continue
                break
            for call in response.tool_calls:
                name = call["name"]
                counts[name] = counts.get(name, 0) + 1
                if name not in tools.names:
                    raise ValueError(f"도구 호출 권한 초과: {name}")
                if counts[name] > (8 if name == "get_file" else 3):
                    messages.append(
                        ToolMessage(
                            content=encode(
                                {
                                    "error": "이 도구의 호출 한도에 도달했습니다. 다른 도구를 사용하거나 현재 근거로 탐색을 마치세요."
                                }
                            ),
                            tool_call_id=call["id"],
                        )
                    )
                    continue
                if time.monotonic() - started >= self.timeout:
                    raise TimeoutError("영향 탐색 제한 시간 초과")
                try:
                    logger.info("조회 tool=%s", name)
                    result = getattr(tools, name)(**call["args"])
                    # 잘린 결과를 완전한 근거로 쓰지 않도록 초과 응답은 오류로 돌린다.
                    text = encode(result)
                    if len(text) > 12000:
                        text = encode(
                            {
                                "error": "결과가 큽니다. 검색 범위와 max_results를 줄이세요"
                            }
                        )
                    else:
                        records.append(
                            {"tool": name, "args": call["args"], "result": result}
                        )
                except (ToolError, ValueError, TypeError, RuntimeError) as exc:
                    text = encode({"error": str(exc)})
                messages.append(ToolMessage(content=text, tool_call_id=call["id"]))
        else:
            raise ValueError("영향 탐색 턴 한도 초과")
        # 키 검색이 놓치는 하드코딩 수치도 후보로 모은다. 선정 판단은 모델에 맡긴다.
        if "search_code" in tools.names and counts.get("search_code", 0) < 3:
            terms = set()
            for req in state["requirements"]:
                for value in re.findall(r"\d+(?:\.\d+)?", req.old_value or ""):
                    number = float(value)
                    terms.add(re.escape(value))
                    if number >= 1 and "%" in (req.old_text or ""):
                        terms.add(re.escape(f"{number / 100:g}"))
                    if number.is_integer() and "세" in (req.old_text or ""):
                        terms.update(re.escape(str(int(n))) for n in (number - 1, number * 12))
            if terms:
                self._collect_evidence(tools, records, "search_code", {"query": "|".join(sorted(terms)), "regex": True})
        # 검색 한 줄만 보고 끝내는 모델을 보완해 후보 파일의 본문을 공급한다.
        if "get_file" in tools.names:
            loaded = {r["args"]["path"] for r in records if r["tool"] == "get_file"}
            paths = dict.fromkeys(
                row["file"] for r in records if r["tool"] in ("search_code", "find_usages")
                for row in r["result"] if isinstance(row, dict) and row.get("file") and row.get("kind") != "test"
            )
            for path in paths:
                if path not in loaded and len(loaded) < 8:
                    if self._collect_evidence(tools, records, "get_file", {"path": path}):
                        loaded.add(path)
        items = []
        # 같은 후보를 여러 요건에 잘못 연결하지 않도록 요건별로 정리한다.
        for req in state["requirements"]:
            logger.info("영향 위치 정리 requirement=%s", req.id)
            items.extend(self._ask(
                "locations-output.md", LocationsOutput,
                {"task": {**payload, "requirements": [req]}, "evidence": records},
            ).items)
        self._ground_locations(items, records)
        return items

    @staticmethod
    def _collect_evidence(tools, records, name, args):
        logger.info("본문·검색 보충 tool=%s", name)
        try:
            result = getattr(tools, name)(**args)
            if len(encode(result)) <= 12000:
                records.append({"tool": name, "args": args, "result": result})
                return True
        except (ToolError, ValueError, TypeError, RuntimeError) as exc:
            logger.warning("조회 보충 실패 tool=%s: %s", name, exc)

    @staticmethod
    def _ground_locations(items, records):
        hits, rules, files, products = [], [], {}, set()

        def rows(value):
            if isinstance(value, list):
                for row in value:
                    yield from rows(row)
            elif isinstance(value, dict):
                yield value
                for row in value.values():
                    yield from rows(row)

        for record in records:
            if record["tool"] in ("search_code", "find_usages"):
                hits.extend(rows(record["result"]))
            elif record["tool"] == "get_product_rules":
                rules.extend(rows(record["result"]))
            elif record["tool"] == "get_products":
                products.update(row["productId"] for row in rows(record["result"]) if row.get("productId"))
            elif record["tool"] == "get_file":
                result = record["result"]
                files[record["args"]["path"]] = (
                    result if isinstance(result, str) else result.get("content", "")
                )
        for spec in items:
            if spec.needs_review or (spec.is_target and (not spec.before.strip() or not spec.after.strip())):
                spec.needs_review, spec.is_target = True, False
                spec.reason += " / 추가 확인 필요: 관련성 또는 변경 전후 설명 부족"
            if spec.kind == "new":
                continue  # 신규 위치는 관측한 파일이라고 주장하지 않는다. 티켓만 만든다.
            if spec.kind in ("db", "product_rule"):
                ids = set(re.findall(r"\bR\d+\b", spec.symbol))
                matches = list(
                    {
                        row["ruleId"]: row for row in rules if row.get("ruleId") in ids
                    }.values()
                )
                if len(matches) != 1:
                    LlmReasoner._defer_location(spec, "업무 규칙 ID를 조회 결과에서 확인할 수 없음")
                    continue
                # ID로 원본을 찾고 나머지 표기를 고정한다. 0.40/0.4 차이를 허위 근거로 오판하지 않는다.
                row = matches[0]
                spec.file = "db/product_rules"
                spec.line = int(row["ruleId"].lstrip("R"))
                spec.symbol = f"{row['ruleId']} {row['productId']}.{row['ruleKey']}"
                spec.snippet = f"{row['ruleKey']} = {row['value']}"
                if spec.is_target and row['productId'] not in products:
                    spec.needs_review, spec.is_target = True, False
                    spec.reason += " / 추가 확인 필요: 상품 설명 미조회"
                continue
            snippet = spec.snippet.strip()
            lines = files.get(spec.file, "").splitlines()
            found = bool(snippet) and (
                any(row.get("file") == spec.file and row.get("line") == spec.line
                    and str(row.get("snippet", "")).strip() == snippet for row in hits)
                or 0 < spec.line <= len(lines) and lines[spec.line - 1].strip() == snippet
            )
            if not found and snippet:
                # 원문이 파일에서 한 번만 나타날 때만 잘못 적힌 줄 번호를 보정한다.
                positions = {i for i, line in enumerate(lines, 1) if line.strip() == snippet}
                if not lines:
                    positions = {row["line"] for row in hits
                                 if row.get("file") == spec.file and row.get("line", 0) > 0
                                 and str(row.get("snippet", "")).strip() == snippet}
                if len(positions) == 1:
                    old = spec.location
                    spec.line = positions.pop()
                    logger.info("근거로 줄 번호 보정 %s → %s", old, spec.location)
                    found = True
            if not found:
                LlmReasoner._defer_location(spec, "코드 원문·위치를 조회 결과에서 유일하게 확인할 수 없음")
                continue
            # 검색 한 줄만으로 주변 로직의 의미를 확정하지 않는다.
            if spec.is_target and not files.get(spec.file, "").strip():
                spec.needs_review, spec.is_target = True, False
                spec.reason += " / 추가 확인 필요: 파일 본문 미조회"

    @staticmethod
    def _defer_location(spec, reason):
        claimed = spec.location
        spec.is_target, spec.needs_review = False, True
        spec.line, spec.snippet = 0, ""
        spec.reason += f" / 추가 확인 필요: {reason} (모델 제안 위치: {claimed})"
        logger.warning("위치 확인 보류 %s: %s", claimed, reason)

    def tests(self, state, tools):
        files = {}
        for spec in state["change_specs"]:
            if (
                spec.is_target
                and spec.kind in ("config", "code", "ui")
                and spec.file not in files
            ):
                files[spec.file] = tools.get_file(spec.file)
        items = []
        for req in state["requirements"]:
            specs = [s for s in state["change_specs"] if s.requirement_id == req.id]
            paths = {s.file for s in specs if s.is_target}
            payload = {"requirements": [req], "files": {p: value for p, value in files.items() if p in paths},
                       "change_specs": specs}
            for case in self._tests_for_requirement(payload):
                if case.requirement_id != req.id:
                    raise ValueError("생성 테스트가 요청한 요건과 다릅니다")
                items.append(case.model_copy(update={"id": f"{req.id}:{case.id}"}))
        return items

    def _tests_for_requirement(self, payload):
        files = payload["files"]
        functions = {}
        for path, content in files.items():
            if path.endswith(".py") and isinstance(content, str):
                try:
                    nodes = ast.parse(content).body
                except SyntaxError:
                    continue  # 로컬 mock은 전체 파일이 아닌 발췌문일 수 있다.
                for node in nodes:
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        functions[node.name] = node.args
        for attempt in range(2):
            items = self._ask("tests.md", TestsOutput, payload).items
            errors, invalid = [], set()
            for case in items:
                if not case.code:
                    continue
                count = len(errors)
                try:
                    tree = ast.parse(case.code)
                    modules = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
                    modules += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
                    # 저장소 모듈 import 또는 실제 파일 읽기 근거가 있어야 한다.
                    roots = {path.split("/")[1] for path in files if path.startswith("src/") and len(path.split("/")) > 2}
                    project_import = any(m.removeprefix("src.").split(".")[0] in roots for m in modules)
                    literals = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
                    file_read = any(path in literals or all(part in literals for part in path.split("/")) for path in files) and any(
                        isinstance(node, ast.Call) and (
                            isinstance(node.func, ast.Name) and node.func.id == "open" or
                            isinstance(node.func, ast.Attribute) and node.func.attr in ("read_text", "read_bytes", "open")
                        ) for node in ast.walk(tree)
                    )
                    if not project_import and not file_read:
                        errors.append(f"{case.id}: 실제 저장소 함수 import 또는 파일 읽기가 없습니다")
                    for call in ast.walk(tree):
                        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id in functions:
                            args = functions[call.func.id]
                            allowed = {a.arg for a in args.args + args.kwonlyargs}
                            if not args.kwarg and any(k.arg and k.arg not in allowed for k in call.keywords):
                                errors.append(f"{case.id}: {call.func.id}에 없는 인자를 사용했습니다. 허용 인자: {sorted(allowed)}")
                except SyntaxError:
                    errors.append(f"{case.id}: 테스트 문법 오류")
                if len(errors) > count:
                    invalid.add(case.id)
            if not errors:
                return items
            if attempt:
                logger.warning("실행 코드가 없는 테스트는 명세로 보류합니다: %s", sorted(invalid))
                return [case.model_copy(update={"code": None, "description": case.description + " (실제 코드 검증 필요)"})
                        if case.id in invalid else case for case in items]
            payload["correction"] = errors
            payload["previous_tests"] = items
        raise AssertionError("unreachable")

    def draft(self, context):
        return self._ask("design.md", Draft, context)
