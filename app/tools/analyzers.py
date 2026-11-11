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


class AnalyzerError(RuntimeError):
    """A tool could not run. This is different from "the tool found nothing", and must not look like it."""


def _note(errors, message: str):
    if errors is not None:
        errors.append(message)


def _check_output(proc, name: str) -> str:
    if proc.returncode not in (0, 1):  # bandit, ruff and eslint exit 1 when they report findings
        raise AnalyzerError(f"{name} exited with code {proc.returncode}: {(proc.stderr or proc.stdout)[-200:].strip()}")
    if not (proc.stdout or "").strip():  # e.g. "No module named bandit": exit 1 with nothing on stdout
        raise AnalyzerError(f"{name} produced no output: {(proc.stderr or '')[-200:].strip() or 'tool not installed?'}")
    return proc.stdout


def _run(cmd: list, code: str, name: str) -> str:
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "target.py"
        path.write_text(code, encoding="utf-8")
        try:
            proc = subprocess.run(cmd + [str(path)], capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=60)
        except subprocess.TimeoutExpired as e:
            raise AnalyzerError(f"{name} timed out after 60s") from e
        except FileNotFoundError as e:
            raise AnalyzerError(f"{name} could not start: {e}") from e
        return _check_output(proc, name)


def run_bandit(code: str, errors: list | None = None) -> list:
    try:
        data = json.loads(_run([sys.executable, "-m", "bandit", "-f", "json", "-q"], code, "bandit"))
    except (AnalyzerError, json.JSONDecodeError) as e:
        _note(errors, f"bandit: {e}")
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


def run_ruff(code: str, errors: list | None = None) -> list:
    try:
        data = json.loads(_run(
            [sys.executable, "-m", "ruff", "check", "--output-format", "json",
             "--select", "F,B,E9,C90", "--isolated"], code, "ruff"))
    except (AnalyzerError, json.JSONDecodeError) as e:
        _note(errors, f"ruff: {e}")
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


def run_eslint(code: str, errors: list | None = None) -> list:
    """JavaScript analysis: ESLint (recommended + eslint-plugin-security). Needs `npm install` in tools/js."""
    if not eslint_available():
        _note(errors, "eslint: not installed (run `npm install` in tools/js)")
        return []
    try:
        proc = subprocess.run(
            [settings.node_binary, str(ESLINT), "--stdin", "--stdin-filename", "target.js", "-f", "json"],
            input=code, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(JS_DIR),
            timeout=60,
        )
        data = json.loads(_check_output(proc, "eslint"))
    except subprocess.TimeoutExpired:
        _note(errors, "eslint: timed out after 60s")
        return []
    except (AnalyzerError, json.JSONDecodeError, FileNotFoundError) as e:
        _note(errors, f"eslint: {e}")
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


def analyze(code: str, language: str = "python", errors: list | None = None) -> list:
    """Run the analyzers for `language`. Tool failures are appended to `errors` (when given) instead of
    being mistaken for a clean result."""
    if language == "javascript":
        return run_eslint(code, errors)
    return run_bandit(code, errors) + run_ruff(code, errors)
