from types import SimpleNamespace
import pytest
from app.tools import mcp_client


def test_mcp_calls_current_tools_and_closes_thread(monkeypatch):
    calls = []
    class Client:
        def __init__(self, url, **kwargs):
            self.url = url
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def call_tool(self, name, args):
            calls.append((self.url, name, args))
            return SimpleNamespace(data=[{"productId": "P001"}], structured_content=None)
    monkeypatch.setattr(mcp_client, "Client", Client)
    tools = mcp_client.McpTools()
    try:
        assert tools.get_products() == [{"productId": "P001"}]
        tools.diff_versions("r", "v3", "v4")
        assert calls[0][1:] == ("get_products", {})
        assert calls[1][1:] == ("diff_versions", {"regulation_id": "r", "old_version": "v3", "new_version": "v4"})
        with pytest.raises(AttributeError):
            tools.create_draft_pr()
    finally:
        tools.close()
    assert not tools._thread.is_alive()
    tools.close()


def test_mcp_reads_environment_when_created(monkeypatch):
    monkeypatch.setenv("BUSINESS_MCP_URL", "http://localhost:9183/mcp")
    tools = mcp_client.McpTools()
    try:
        assert tools.urls["business"] == "http://localhost:9183/mcp"
        assert "code" not in tools.urls
    finally:
        tools.close()


def test_missing_product_documents_are_reported_without_local_fallback(monkeypatch):
    from fastmcp.exceptions import ToolError
    tools = mcp_client.McpTools()
    def missing(*args):
        raise ToolError("상품 문서가 없습니다")
    monkeypatch.setattr(tools, "get_product_doc", missing)
    try:
        result = tools.get_product_documents(["P999"])
        assert result["documents"] == [] and "P999" in result["data_gaps"][0]
    finally:
        tools.close()


def test_related_regulation_versions_use_primary_effective_date(monkeypatch):
    tools = mcp_client.McpTools()
    calls = []
    catalog = [
        {"regulation_id": "primary", "versions": [{"version": "v4", "effective_from": "2026-12-01"}]},
        {"regulation_id": "related", "versions": [
            {"version": "v1", "effective_from": "2025-01-01"},
            {"version": "v2", "effective_from": "2026-01-01"},
            {"version": "v3", "effective_from": "2027-01-01"}]},
        {"regulation_id": "future", "versions": [{"version": "v1", "effective_from": "2027-01-01"}]},
        {"regulation_id": "undated", "versions": [{"version": "v1", "effective_from": None}]},
    ]
    def call(name, **kw):
        calls.append((name, kw))
        if name == "list_regulations":
            return catalog
        if name == "list_articles":
            return [{"article_id": "1", "title": "목적"}]
        return {"article_id": "1", "uri": "reg://source", "text": "원문", "title": "제목"}
    monkeypatch.setattr(tools, "call", call)
    try:
        result = tools.get_regulation_context("primary", "v4")
        assert [(a["regulation_id"], a["version"]) for a in result["articles"]] == [("primary", "v4")]
        assert result["related"] == [{"regulation_id": "related", "version": "v2", "title": "",
                                     "articles": [{"article_id": "1", "title": "목적"}]}]   # 시행일 이전 최신 버전
        assert "undated" in result["data_gaps"][0]
        assert not any(args.get("version") == "v3" for _, args in calls)
        with pytest.raises(ValueError, match="시행일"):
            tools.get_regulation_context("primary", "v99")
    finally:
        tools.close()


def test_adapter_over_real_mcp_protocol_preserves_sources_and_snapshot():
    from fastmcp import FastMCP
    regulation, business = FastMCP("regulation-test"), FastMCP("business-test")
    observed = []
    for name, owner in mcp_client.TOOL_SERVER.items():
        def unused():
            return []
        (regulation if owner == "regulation" else business).tool(unused, name=name)
    @regulation.tool
    def get_product_doc(product_id: str) -> dict:
        return {"product_id": product_id, "updated_at": "2026-10-20", "sections": [
            {"uri": f"doc://{product_id}#1", "section": "설명", "text": "증액 대환에만 적용한다"},
            {"uri": f"doc://{product_id}#2", "section": "빈 항목", "text": ""}]}
    @business.tool
    def get_product_rules(as_of: str | None = None) -> list[dict]:
        observed.append(as_of)
        return [{"ruleId": "R1"}]
    tools = mcp_client.McpTools({"regulation": regulation, "business": business})
    try:
        tools.check_connection()
        result = tools.get_product_documents(["P008"])
        assert result["documents"][0]["uri"] == "doc://P008#1"
        assert "증액 대환" in result["documents"][0]["content"]
        assert len(result["documents"]) == 1 and not result["data_gaps"]
        assert tools.get_product_rules(as_of="2026-11-30") == [{"ruleId": "R1"}]
        assert observed == ["2026-11-30"]
    finally:
        tools.close()


def test_old_mcp_server_is_rejected_before_analysis():
    from fastmcp import FastMCP
    tools = mcp_client.McpTools({"regulation": FastMCP("outdated")})
    try:
        with pytest.raises(ValueError, match="최신 main"):
            tools.check_connection()
    finally:
        tools.close()


def test_product_document_identity_must_match_request(monkeypatch):
    tools = mcp_client.McpTools()
    monkeypatch.setattr(tools, "get_product_doc", lambda pid: {"product_id": "P002", "sections": []})
    try:
        with pytest.raises(ValueError, match="상품 ID"):
            tools.get_product_documents(["P001"])
    finally:
        tools.close()
