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

    code, language, warnings, findings, errors = state["code"], state.get("language", "python"), [], None, []
    if language == "javascript" and not eslint_available():
        warnings.append("ESLint is not installed (run `npm install` in tools/js); JavaScript static analysis skipped.")
        return {"static_findings": [], "warnings": warnings}
    if settings.use_mcp:
        try:
            result = await asyncio.wait_for(call_tool("analyze_code", {"code": code, "language": language}),
                                            timeout=settings.mcp_timeout)
            if isinstance(result, dict):
                findings, errors = result.get("findings", []), list(result.get("errors", []))
            else:  # older server: a bare list
                findings = result
        except Exception as e:  # noqa: BLE001  (includes asyncio.TimeoutError, which has an empty message)
            warnings.append(f"MCP server unavailable ({type(e).__name__}: {e}); used direct tool calls instead.")
    if findings is None:
        findings = await asyncio.to_thread(analyze, code, language, errors)
    warnings += [f"Static analyzer problem: {e}" for e in errors]
    return {"static_findings": findings, "warnings": warnings}
