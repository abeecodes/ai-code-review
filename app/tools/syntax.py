"""Syntax checks used to reject generated tests / fixes before they are run."""
import ast
import re
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


def _extract_defined_symbols(code: str) -> set[str]:
    """Extract top-level function, class, and variable names from source code."""
    try:
        tree = ast.parse(code)
    except Exception:
        return set()
    symbols = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    symbols.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            symbols.add(node.target.id)
    return symbols


_TEST_NAME = re.compile(r"^test_f(\d+)_")
_ASSERT_CALLS = {"raises", "warns", "fail", "approx"}


def _has_assertion(fn) -> bool:
    for node in ast.walk(fn):
        if isinstance(node, ast.Assert):
            return True
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if name in _ASSERT_CALLS:
                return True
    return False


def _calls_name(fn, names: set) -> bool:
    return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in names
               for n in ast.walk(fn))


def _test_functions(tree) -> list:
    """Test functions at module level and inside Test* classes (what pytest collects)."""
    found = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            found.append(node)
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            found += [m for m in node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                      and m.name.startswith("test_")]
    return found


def validate_test_structure(test_code: str, target_code: str, language: str = "python",
                            finding_ids=None) -> str | None:
    """Structural checks on generated tests. The returned text is sent back to the model as feedback.

    Rejects tests that could never produce evidence: no import of the target, no assertions, a missing
    `import pytest`, calls to functions that do not exist, and (when finding_ids is given) names that
    cannot be linked to a finding."""
    syn = syntax_error(test_code, language)
    if syn:
        return f"syntax error: {syn}"

    if language != "python":
        if "target" not in test_code:
            return "the test file must import or require './target.js'"
        if finding_ids is not None:
            if not re.search(r"""test\(\s*['"]test_f\d+_""", test_code):
                return "no test is named test_<finding_id>_<category>_<description> (for example 'test_f1_empty_input')"
            if "assert" not in test_code:
                return "the tests contain no assertions (use assert.strictEqual / assert.throws)"
        return None

    try:
        tree = ast.parse(test_code)
    except Exception as e:
        return f"syntax error: {e}"

    # 1. the module under test is imported, and so is pytest if it is used
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {(a.asname or a.name).split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    if "target" not in imported:
        return "the test file must import the module under test as 'target' ('import target')"
    if any(isinstance(n, ast.Name) and n.id == "pytest" for n in ast.walk(tree)) and "pytest" not in imported:
        return "the tests use 'pytest' but do not import it; add 'import pytest' at the top"

    # 2. there are test functions
    test_funcs = _test_functions(tree)
    if not test_funcs:
        return "no test functions found; test names must start with 'test_'"

    # 3. every test has an assertion (directly, or through a helper that asserts)
    helpers = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)
               and not n.name.startswith("test_") and _has_assertion(n)}
    for fn in test_funcs:
        if not _has_assertion(fn) and not _calls_name(fn, helpers):
            return f"test '{fn.name}' has no assertion; a test without one passes on any code"

    # 4. every test can be linked to a finding
    if finding_ids is not None:
        for fn in test_funcs:
            m = _TEST_NAME.match(fn.name)
            if not m:
                return (f"test '{fn.name}' must be named test_<finding_id>_<category>_<description>, "
                        f"for example test_f1_empty_list; valid finding ids: {sorted(finding_ids)}")
            if f"f{m.group(1)}" not in finding_ids:
                return f"test '{fn.name}' refers to unknown finding f{m.group(1)}; valid ids: {sorted(finding_ids)}"

    # 5. functions called on `target` exist in the code under test
    target_symbols = _extract_defined_symbols(target_code)
    if target_symbols:  # only validate if target parsed cleanly
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "target":
                if node.attr not in target_symbols and not node.attr.startswith("__"):
                    return f"test calls 'target.{node.attr}' which does not exist in the code under test"

    return None
