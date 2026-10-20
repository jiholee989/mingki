"""MCP 프로토콜을 거쳐 호출되는지 확인 (Agent가 보는 모습 그대로)."""

import pytest
from fastmcp import Client
from fastmcp.exceptions import ResourceError, ToolError

from regulation_mcp.server import mcp


async def test_tools_are_registered():
    async with Client(mcp) as c:
        names = {t.name for t in await c.list_tools()}
    assert names == {
        "diff_versions", "search_regulation", "get_article", "list_articles", "search_product_docs", "get_product_doc",
    }


async def test_diff_versions_over_mcp():
    async with Client(mcp) as c:
        r = await c.call_tool("diff_versions", {"regulation_id": "credit-loan-ops", "old_version": "v3", "new_version": "v4"})
    assert r.data["effective_from"] == "2026-12-01"
    assert any(ch["article_id"] == "15-2" for ch in r.data["changes"])


async def test_search_regulation_over_mcp():
    async with Client(mcp) as c:
        r = await c.call_tool("search_regulation", {"query": "고령자 기준", "regulation_id": "credit-loan-ops"})
    assert any(h["uri"] == "reg://credit-loan-ops/v4/15" for h in r.data)  # 버전을 생략하면 최신(v4)


async def test_search_regulation_defaults_to_all_regulations():
    async with Client(mcp) as c:
        r = await c.call_tool("search_regulation", {"query": "고령 금융소비자 녹취"})
    assert r.data[0]["regulation_id"] == "senior-protection"


async def test_product_doc_tools_over_mcp():
    async with Client(mcp) as c:
        hits = (await c.call_tool("search_product_docs", {"query": "조력자 안내", "product_id": "P002"})).data
        doc = (await c.call_tool("get_product_doc", {"product_id": "P010"})).data
        text = (await c.read_resource("doc://P008"))[0].text
    assert hits and all(h["product_id"] == "P002" for h in hits)
    assert doc["uri"] == "doc://P010" and any(s["section"] == "심사 절차" for s in doc["sections"])
    assert "DSR 40% 이내" in text


async def test_product_doc_out_of_scope_is_tool_error():
    async with Client(mcp) as c:
        with pytest.raises(ToolError, match="product_id"):
            await c.call_tool("get_product_doc", {"product_id": "../README"})


async def test_out_of_scope_is_tool_error():
    async with Client(mcp) as c:
        with pytest.raises(ToolError, match="regulation_id"):
            await c.call_tool("search_regulation", {"query": "정답", "regulation_id": "../../eval", "version": "answer_key"})


async def test_article_resource():
    async with Client(mcp) as c:
        text = (await c.read_resource("reg://credit-loan-ops/v4/15"))[0].text
        title = (await c.read_resource("reg://credit-loan-ops/v4"))[0].text
    assert "60" in text
    assert title == "개인신용대출 운영기준"


async def test_missing_article_resource_errors():
    async with Client(mcp) as c:
        with pytest.raises(Exception):
            await c.read_resource("reg://credit-loan-ops/v4/999")
