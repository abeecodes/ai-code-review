import asyncio

from app.agent.modes import flags
from app.agent.nodes.common import timed
from app.core.config import settings
from app.mcp_tools.client import call_tool
from app.tools.analyzers import analyze, eslint_available


@timed("static_analysis")
async def static_analysis_node(state):
    if not flags(state)["static"]:
        return {"static_findings": []}

    code, language, warnings, findings = state["code"], state.get("language", "python"), [], None
    if language == "javascript" and not eslint_available():
        warnings.append("ESLint is not installed (run `npm install` in tools/js); JavaScript static analysis skipped.")
        return {"static_findings": [], "warnings": warnings}
    if settings.use_mcp:
        try:
            findings = await call_tool("analyze_code", {"code": code, "language": language})
        except Exception as e:  # noqa: BLE001
            warnings.append(f"MCP server unavailable, used direct tool calls instead: {e}")
    if findings is None:
        findings = await asyncio.to_thread(analyze, code, language)
    return {"static_findings": findings, "warnings": warnings}
