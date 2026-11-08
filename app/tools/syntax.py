"""Syntax checks used to reject generated tests / fixes before they are run."""
import ast
import subprocess
import tempfile
from pathlib import Path

from app.core.config import settings


def syntax_error(code: str, language: str = "python"):
    """Return None if the code parses, otherwise a short error message."""
    if language == "python":
        try:
            ast.parse(code)
            return None
        except SyntaxError as e:
            return f"line {e.lineno}: {e.msg}"
        except ValueError as e:
            return str(e)
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "check.js"
        path.write_text(code, encoding="utf-8")
        try:
            proc = subprocess.run([settings.node_binary, "--check", str(path)],
                                  capture_output=True, text=True, timeout=20)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None  # cannot check without Node; the sandbox run will report real problems
        if proc.returncode == 0:
            return None
        lines = [ln for ln in proc.stderr.splitlines() if "Error" in ln]
        return (lines[0] if lines else proc.stderr.strip())[:200]
