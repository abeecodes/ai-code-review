import shutil

import pytest

from app.core.config import settings
from app.sandbox.runner import count_tests, is_blocked, run_tests

BUGGY = "def average(xs):\n    return sum(xs) / len(xs)\n"
TESTS = """
import pytest, target

def test_f1_normal_average():
    assert target.average([2, 4]) == 3

def test_f1_empty_list_rejected():
    with pytest.raises(ValueError):
        target.average([])
"""


def test_failed_test_confirms_defect():
    res = run_tests(BUGGY, TESTS)
    assert res and res[0]["status"] != "error", res
    by_name = {r["name"]: r for r in res}
    assert by_name["test_f1_normal_average"]["status"] == "passed"
    assert by_name["test_f1_empty_list_rejected"]["status"] in ("failed", "error")
    assert by_name["test_f1_empty_list_rejected"]["finding_id"] == "f1"
    assert by_name["test_f1_empty_list_rejected"]["category"] == "empty"


def test_blocked_module_is_rejected():
    res = run_tests(BUGGY, "import subprocess\ndef test_f1_x():\n    pass\n")
    assert res[0]["status"] == "error" and "blocked" in res[0]["message"]
    assert is_blocked("import socket", "python") and is_blocked("require('child_process')", "javascript")


def test_whole_run_timeout(monkeypatch):
    monkeypatch.setattr(settings, "sandbox_timeout", 2)
    res = run_tests("import time\ntime.sleep(10)\n", "import target\ndef test_f1_x():\n    pass\n")
    assert res[0]["status"] == "timeout"


def test_per_test_timeout_does_not_stop_other_tests(monkeypatch):
    monkeypatch.setattr(settings, "per_test_timeout", 1)
    code = ("import time, target\n\ndef test_f1_hang():\n    time.sleep(30)\n\n"
            "def test_f2_ok():\n    assert target.noop() == 1\n")
    res = {r["name"]: r["status"] for r in run_tests("def noop():\n    return 1\n", code)}
    assert res == {"test_f1_hang": "timeout", "test_f2_ok": "passed"}


def test_secrets_are_not_visible_to_generated_tests(monkeypatch):
    monkeypatch.setenv("MY_SECRET_API_KEY", "super-secret")
    code = ("import os, target\n\ndef test_f1_env():\n"
            "    assert not [k for k in os.environ if 'KEY' in k or 'SECRET' in k]\n")
    res = run_tests("def noop():\n    pass\n", code)
    assert res[0]["status"] == "passed", res


def test_count_tests():
    assert count_tests("def test_a():\n  pass\ndef test_b():\n  pass\ndef helper():\n  pass") == 2
    assert count_tests("test('a', () => {});\ntest('b', () => {});", "javascript") == 2


needs_node = pytest.mark.skipif(shutil.which(settings.node_binary) is None, reason="Node.js not installed")


@needs_node
def test_javascript_tests_run_and_confirm_defect():
    code = "function average(n) {\n  return n.reduce((a, b) => a + b, 0) / n.length;\n}\n"  # no exports on purpose
    tests = """
const test = require('node:test');
const assert = require('node:assert');
const target = require('./target.js');
test('test_f1_normal_average', { timeout: 3000 }, () => { assert.strictEqual(target.average([2, 4]), 3); });
test('test_f1_empty_array_returns_zero', { timeout: 3000 }, () => { assert.strictEqual(target.average([]), 0); });
"""
    res = {r["name"]: r["status"] for r in run_tests(code, tests, "javascript")}
    assert res == {"test_f1_normal_average": "passed", "test_f1_empty_array_returns_zero": "failed"}


@needs_node
def test_javascript_syntax_check():
    from app.tools.syntax import syntax_error
    assert syntax_error("function f( {", "javascript")
    assert syntax_error("function f() { return 1; }", "javascript") is None
    assert syntax_error("def f(:", "python")
