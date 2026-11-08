import json

import pytest

from app.core.config import settings


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Every test gets its own cache/data folders and never touches a real model or MCP subprocess."""
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path / "cache"))
    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "use_mcp", False)
    monkeypatch.setattr(settings, "llm_cache", False)
    monkeypatch.setattr(settings, "per_test_timeout", 3)


class FakeLLM:
    """Routes by system prompt, so the real graph, retry loop and sandbox run end to end."""

    def __init__(self, review=None, tests=None, fix=None):
        self.review, self.tests, self.fix = review, list(tests or []), fix
        self.calls = []

    async def __call__(self, system, user):
        if "senior code reviewer" in system:
            self.calls.append("review")
            out = self.review
        elif "write pytest tests" in system or "write Node.js tests" in system:
            self.calls.append("tests")
            out = {"test_code": self.tests.pop(0) if len(self.tests) > 1 else self.tests[0]}
        elif "repair code" in system:
            self.calls.append("fix")
            out = {"fixed_code": self.fix}
        else:
            raise AssertionError("unexpected prompt")
        return json.dumps(out), 100, 50


@pytest.fixture
def install_llm(monkeypatch):
    def install(**kw):
        fake = FakeLLM(**kw)
        monkeypatch.setattr("app.agent.llm._complete", fake)
        return fake
    return install


BUGGY = "def average(numbers):\n    return sum(numbers) / len(numbers)\n"
FIXED = ("def average(numbers):\n    if not numbers:\n        raise ValueError('empty')\n"
         "    return sum(numbers) / len(numbers)\n")
REVIEW = {"summary": "Crashes on empty input.", "quality_score": 55, "findings": [
    {"line": 2, "severity": "medium", "category": "bug", "title": "Division by zero on empty list",
     "explanation": "len is 0", "failure_scenario": "average([])", "fix": "raise ValueError", "source": "llm"}]}
GOOD_TESTS = """
import pytest, target

def test_f1_normal_average():
    assert target.average([2, 4]) == 3

def test_f1_empty_list_raises_value_error():
    with pytest.raises(ValueError):
        target.average([])
"""
