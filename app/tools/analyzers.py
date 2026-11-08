"""Static analysis tools (bandit + ruff). Used directly and through the MCP server."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from app.core.config import settings

JS_DIR = Path(__file__).resolve().parents[2] / "tools" / "js"
ESLINT = JS_DIR / "node_modules" / "eslint" / "bin" / "eslint.js"
_ESLINT_SECURITY = {"no-eval", "no-implied-eval", "no-new-func"}

_SEV = {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}


def _run(cmd: list, code: str) -> str:
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "target.py"
        path.write_text(code, encoding="utf-8")
        proc = subprocess.run(cmd + [str(path)], capture_output=True, text=True, timeout=60)
        return proc.stdout


def run_bandit(code: str) -> list:
    try:
        out = _run([sys.executable, "-m", "bandit", "-f", "json", "-q"], code)
        data = json.loads(out or "{}")
    except Exception:  # noqa: BLE001
        return []
    return [
        {
            "source": "bandit",
            "line": r.get("line_number"),
            "severity": _SEV.get(r.get("issue_severity", "LOW"), "low"),
            "category": "security",
            "title": f"{r.get('test_id')} {r.get('test_name')}",
            "explanation": r.get("issue_text", ""),
        }
        for r in data.get("results", [])
    ]


def run_ruff(code: str) -> list:
    try:
        out = _run(
            [sys.executable, "-m", "ruff", "check", "--output-format", "json",
             "--select", "F,B,E9,C90", "--isolated"],
            code,
        )
        data = json.loads(out or "[]")
    except Exception:  # noqa: BLE001
        return []
    return [
        {
            "source": "ruff",
            "line": (r.get("location") or {}).get("row"),
            "severity": "medium" if str(r.get("code", "")).startswith(("F", "B", "E9")) else "low",
            "category": "maintainability" if str(r.get("code", "")).startswith("C90") else "bug",
            "title": f"{r.get('code')}",
            "explanation": r.get("message", ""),
        }
        for r in data
    ]


def eslint_available() -> bool:
    return ESLINT.exists()


def run_eslint(code: str) -> list:
    """JavaScript analysis: ESLint (recommended + eslint-plugin-security). Needs `npm install` in tools/js."""
    if not eslint_available():
        return []
    try:
        proc = subprocess.run(
            [settings.node_binary, str(ESLINT), "--stdin", "--stdin-filename", "target.js", "-f", "json"],
            input=code, capture_output=True, text=True, cwd=str(JS_DIR), timeout=60,
        )
        data = json.loads(proc.stdout or "[]")
    except Exception:  # noqa: BLE001
        return []
    out = []
    for file_result in data:
        for m in file_result.get("messages", []):
            rule = m.get("ruleId") or "parse-error"
            if m.get("fatal"):
                sev, cat = "high", "bug"
            elif rule.startswith("security/") or rule in _ESLINT_SECURITY:
                sev, cat = "high", "security"
            elif rule == "eqeqeq" or m.get("severity") == 2:
                sev, cat = "medium", "bug"
            else:
                sev, cat = "low", "maintainability"
            out.append({"source": "eslint", "line": m.get("line"), "severity": sev, "category": cat,
                        "title": rule, "explanation": m.get("message", "")})
    return out


def analyze(code: str, language: str = "python") -> list:
    if language == "javascript":
        return run_eslint(code)
    return run_bandit(code) + run_ruff(code)
