"""regulation-mcp (평가표의 rag-mcp 역할): 규정 원문 비교 · 조항 원문 · 규정과 상품 문서 검색(Vector DB + 키워드).

실행:
    uv run python -m regulation_mcp.server          # HTTP  http://127.0.0.1:8001/mcp
    uv run python -m regulation_mcp.server --stdio  # stdio (로컬 Client 테스트용)
"""

import os
import sys

from fastmcp import FastMCP
from fastmcp.exceptions import ResourceError, ToolError

from regulation_mcp import product_docs as docs
from regulation_mcp import regulations as reg
from regulation_mcp import search
from regulation_mcp.regulations import RegulationError

mcp = FastMCP(
    "regulation-mcp",
    instructions=(
        "은행 내규(규정) 원문과 상품설명서 · 업무 절차 문서 도구. 어떤 규정이 있는지는 list_regulations로 먼저 본다. 규정 조항 ID는 '15', '15-2'(제15조의2), "
        "'supp-2'(부칙 제2조) 형식이고 원문 링크는 reg://{regulation_id}/{version}/{article_id} 이다. "
        "상품 문서 링크는 doc://{product_id}#{섹션 번호} 이다. 문서에 없는 절차는 지어내지 말고 추가 확인이 필요하다고 답한다."
    ),
)


def _tool_error(e: RegulationError) -> ToolError:
    return ToolError(str(e))


@mcp.tool(annotations={"readOnlyHint": True})
def list_regulations() -> list[dict]:
    """규정 목록. 어떤 규정 · 버전이 있는지 모를 때 먼저 부른다.

    applies_to는 규정이 적용되는 상품 ID 목록이다. null이면 원문에 적용 상품 정보가 없는 것이므로
    상품 문서 · 상품 규칙으로 판단한다.

    Returns:
        [{regulation_id, title, latest_version, applies_to: [product_id] | null,
          versions: [{version, effective_from, previous_version, uri}]}]
    """
    try:
        return reg.list_regulations()
    except RegulationError as e:
        raise _tool_error(e) from e


@mcp.tool(annotations={"readOnlyHint": True})
def diff_versions(regulation_id: str, old_version: str | None = None, new_version: str | None = None) -> dict:
    """신·구 규정을 조항 단위로 비교해 바뀐 조항만 돌려준다 (원문 기준, 결정적).

    표현만 바뀐 조항도 포함된다. 실질 변경인지는 호출한 쪽이 판단한다.

    Args:
        regulation_id: 규정 ID (예: "credit-loan-ops")
        old_version: 구 버전 (예: "v3"). 생략하면 new_version의 이전 버전
        new_version: 신 버전 (예: "v4"). 생략하면 최신 버전

    Returns:
        {regulation_id, old_version, new_version, effective_from,
         changes: [{article_id, title, change: "added"|"removed"|"modified",
                    old_text, new_text, old_uri, new_uri}]}
    """
    try:
        return reg.diff_versions(regulation_id, old_version, new_version)
    except RegulationError as e:
        raise _tool_error(e) from e


@mcp.tool(annotations={"readOnlyHint": True})
def search_regulation(query: str, regulation_id: str | None = None, version: str | None = None) -> list[dict]:
    """규정 조항 검색 (의미 + 키워드 혼합). 관련도 순으로 최대 5개.

    원문에 없는 표현으로 물어도 되고(예: "노인으로 보는 나이"), 숫자 · 약어(예: "DSR 40%")도 찾는다.
    regulation_id를 생략하면 모든 규정의 최신 버전에서 찾는다. 규정마다 같은 말을 다르게 정의할 수 있으니
    결과의 regulation_id를 확인한다.

    Args:
        query: 질문이나 검색어 (예: "고령자로 보는 나이 기준", "DSR 한도")
        regulation_id: 규정 ID (예: "credit-loan-ops"). 생략하면 전체 규정
        version: 버전 (예: "v4"). 생략하면 최신. regulation_id와 함께만 쓴다

    Returns:
        [{uri, regulation_id, version, article_id, title, text}] 관련도 순
    """
    try:
        return search.index().search_regulations(query, regulation_id, version)
    except RegulationError as e:
        raise _tool_error(e) from e


@mcp.tool(annotations={"readOnlyHint": True})
def search_product_docs(query: str, product_id: str | None = None) -> list[dict]:
    """상품설명서 · 업무 절차 문서 검색 (의미 + 키워드 혼합). 섹션 단위로 관련도 순 최대 5개.

    심사 절차, 설명 · 동의 항목, 기록 보관, 화면 · 설명서 안내 문구처럼 상품 규칙 숫자로 표현되지 않는 정보를 찾는다.

    Args:
        query: 질문이나 검색어 (예: "DSR 안내 문구", "고령 고객 녹취")
        product_id: 상품 ID (예: "P001"). 생략하면 모든 상품

    Returns:
        [{uri, product_id, name, section, text, updated_at}] 관련도 순
    """
    try:
        return search.index().search_docs(query, product_id)
    except RegulationError as e:
        raise _tool_error(e) from e


@mcp.tool(annotations={"readOnlyHint": True})
def get_product_doc(product_id: str) -> dict:
    """상품 하나의 설명서 · 업무 절차 문서 전체. 섹션이 비어 있거나 없으면 그 내용은 문서에 없는 것이다.

    Returns:
        {uri, product_id, name, updated_at, sections: [{uri, section, text}]}
    """
    try:
        return docs.get_doc(product_id)
    except RegulationError as e:
        raise _tool_error(e) from e


@mcp.tool(annotations={"readOnlyHint": True})
def get_article(regulation_id: str, version: str, article_id: str) -> dict:
    """조항 하나의 원문. Resource reg://{regulation_id}/{version}/{article_id} 와 같은 내용.

    Returns:
        {uri, article_id, title, text}
    """
    try:
        return reg.get_article(regulation_id, version, article_id)
    except RegulationError as e:
        raise _tool_error(e) from e


@mcp.tool(annotations={"readOnlyHint": True})
def list_articles(regulation_id: str, version: str | None = None) -> list[dict]:
    """버전 하나의 조항 목록 (본문 제외).

    Args:
        regulation_id: 규정 ID (예: "credit-loan-ops")
        version: 버전 (예: "v4"). 생략하면 최신 버전

    Returns:
        [{uri, article_id, title}]
    """
    try:
        return reg.list_articles(regulation_id, version or reg.latest_version(regulation_id))
    except RegulationError as e:
        raise _tool_error(e) from e


@mcp.resource("reg://{regulation_id}/{version}/{article_id}", mime_type="text/plain")
def article_resource(regulation_id: str, version: str, article_id: str) -> str:
    """조항 원문 (신·구 원문 링크)."""
    try:
        return reg.get_article(regulation_id, version, article_id)["text"]
    except RegulationError as e:
        raise ResourceError(str(e)) from e


@mcp.resource("reg://{regulation_id}/{version}", mime_type="text/plain")
def regulation_resource(regulation_id: str, version: str) -> str:
    """규정 제목 (버전 링크)."""
    try:
        return reg.load(regulation_id, version)["meta"].get("title", regulation_id)
    except RegulationError as e:
        raise ResourceError(str(e)) from e


@mcp.resource("doc://{product_id}", mime_type="text/plain")
def product_doc_resource(product_id: str) -> str:
    """상품 문서 원문."""
    try:
        d = docs.get_doc(product_id)
    except RegulationError as e:
        raise ResourceError(str(e)) from e
    return "\n\n".join([f"# {d['name']} ({d['updated_at']})"] + [f"## {x['section']}\n{x['text']}" for x in d["sections"]])


if __name__ == "__main__":
    if "--stdio" in sys.argv:
        mcp.run(transport="stdio")
    else:
        mcp.run(
            transport="http",
            host=os.environ.get("HOST", "127.0.0.1"),
            port=int(os.environ.get("PORT", 8001)),
            path="/mcp",
        )
