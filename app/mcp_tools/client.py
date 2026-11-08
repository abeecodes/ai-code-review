"""MCP client used by the LangGraph static-analysis node."""
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[2]


async def call_tool(name: str, arguments: dict):
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "app.mcp_tools.server"], cwd=str(ROOT)
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments)
            text = "".join(getattr(c, "text", "") for c in result.content)
            return json.loads(text or "[]")
