from types import SimpleNamespace

from app.tools import mcp_client


def test_mcp_discovers_tools_calls_and_closes_thread(monkeypatch):
    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def list_tools(self):
            return [
                SimpleNamespace(
                    name="search_code",
                    description="코드 검색",
                    input_schema={
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                    },
                )
            ]

        async def call_tool(self, name, args):
            return SimpleNamespace(
                data=[{"file": "loan.py", "line": 1}], structured_content=None
            )

        async def read_resource(self, uri):
            return [SimpleNamespace(text="규정 원문")]

    monkeypatch.setattr(mcp_client, "Client", Client)
    tools = mcp_client.McpTools()
    try:
        assert tools.describe("search_code")[0]["function"]["name"] == "search_code"
        assert tools.search_code("DSR")[0]["file"] == "loan.py"
        assert tools.read_resource("reg://r/v4/8") == "규정 원문"
    finally:
        tools.close()
    assert not tools._thread.is_alive()
    tools.close()


def test_mcp_reads_environment_when_created(monkeypatch):
    monkeypatch.setenv("CODE_MCP_URL", "http://localhost:9182/mcp")
    tools = mcp_client.McpTools()
    try:
        assert tools.urls["code"] == "http://localhost:9182/mcp"
    finally:
        tools.close()
