"""LLM 판단과 제한된 읽기 도구 루프. 외부 쓰기는 이 모듈에 제공하지 않는다."""

import json
import logging
import os
import re
import time
from pathlib import Path

from fastmcp.exceptions import ToolError
from pydantic import ValidationError
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from app.reasoning import Draft, LocationsOutput, RequirementsOutput, TestsOutput

logger = logging.getLogger(__name__)
PROMPTS = Path(__file__).resolve().parents[1] / "prompts"


def encode(value):
    return json.dumps(
        value, ensure_ascii=False, default=lambda v: v.model_dump(mode="json")
    )


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
                    schema, method="function_calling"
                ).invoke(messages)
                output = schema.model_validate(output)
                break
            except ValidationError as exc:
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
        return self._ask("requirement.md", RequirementsOutput, diff).items

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
                break
            for call in response.tool_calls:
                name = call["name"]
                counts[name] = counts.get(name, 0) + 1
                if name not in tools.names:
                    raise ValueError(f"도구 호출 권한 초과: {name}")
                if counts[name] > 3:
                    messages.append(
                        ToolMessage(
                            content=encode(
                                {
                                    "error": "이 도구의 3회 호출 한도에 도달했습니다. 다른 도구를 사용하거나 현재 근거로 탐색을 마치세요."
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
        items = self._ask(
            "locations-output.md",
            LocationsOutput,
            {"task": payload, "evidence": records},
        ).items
        self._ground_locations(items, records)
        return items

    @staticmethod
    def _ground_locations(items, records):
        hits, rules, files = [], [], {}

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
            elif record["tool"] == "get_file":
                result = record["result"]
                files[record["args"]["path"]] = (
                    result if isinstance(result, str) else result.get("content", "")
                )
        for spec in items:
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
                    raise ValueError("업무 규칙의 조회 근거가 없습니다")
                # ID로 원본을 찾고 나머지 표기를 고정한다. 0.40/0.4 차이를 허위 근거로 오판하지 않는다.
                row = matches[0]
                spec.file = "db/product_rules"
                spec.line = int(row["ruleId"].lstrip("R"))
                spec.symbol = f"{row['ruleId']} {row['productId']}.{row['ruleKey']}"
                spec.snippet = f"{row['ruleKey']} = {row['value']}"
                continue
            found = any(
                row.get("file") == spec.file
                and row.get("line") == spec.line
                and str(row.get("snippet", "")).strip() == spec.snippet.strip()
                for row in hits
            )
            lines = files.get(spec.file, "").splitlines()
            found |= (
                0 < spec.line <= len(lines)
                and lines[spec.line - 1].strip() == spec.snippet.strip()
            )
            if not found:
                raise ValueError(f"도구 결과에 없는 코드 위치입니다: {spec.location}")

    def tests(self, state, tools):
        files = {}
        for spec in state["change_specs"]:
            if (
                spec.is_target
                and spec.kind in ("config", "code", "ui")
                and spec.file not in files
            ):
                files[spec.file] = tools.get_file(spec.file)
        return self._ask(
            "tests.md",
            TestsOutput,
            {"requirements": state["requirements"], "files": files},
        ).items

    def draft(self, context):
        return self._ask("design.md", Draft, context)
