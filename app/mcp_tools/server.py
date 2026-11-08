"""MCP server wrapping the code analysis tools (bandit + ruff for Python, ESLint for JavaScript).

Run standalone (stdio):  python -m app.mcp_tools.server
"""
import json

from mcp.server.fastmcp import FastMCP

from app.tools.analyzers import analyze, run_bandit, run_eslint, run_ruff

mcp = FastMCP("code-analysis")


@mcp.tool()
def analyze_code(code: str, language: str = "python") -> str:
    """Analyse source code. language is 'python' (bandit + ruff) or 'javascript' (ESLint). Returns a JSON list."""
    return json.dumps(analyze(code, language))


@mcp.tool()
def bandit_scan(code: str) -> str:
    """Run a bandit security scan on Python source. Returns a JSON list."""
    return json.dumps(run_bandit(code))


@mcp.tool()
def ruff_lint(code: str) -> str:
    """Run ruff lint on Python source. Returns a JSON list."""
    return json.dumps(run_ruff(code))


@mcp.tool()
def eslint_scan(code: str) -> str:
    """Run ESLint (with security plugin) on JavaScript source. Returns a JSON list."""
    return json.dumps(run_eslint(code))


if __name__ == "__main__":
    mcp.run()
