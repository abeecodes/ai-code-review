"""Regression tests for bugs found in the code audit. Each test reproduces the original failure."""
import asyncio
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest
from pydantic import ValidationError

from app import storage
from app.agent import llm
from app.agent.graph import run_review
from app.core.config import Settings, settings
from app.fix_logic import evaluate_fix
from app.sandbox import runner
from app.scoring import failing_tests_by_finding, is_test_infrastructure_bug
from app.tools.syntax import validate_test_structure
from tests.conftest import BUGGY, FIXED, GOOD_TESTS, REVIEW

# ------------------------------------------------------------------ failure classification

NAME_ERROR_IN_TEST = ("def test_f1_x():\n>       with pytest.raises(ValueError):\n"
                      "E       NameError: name 'pytest' is not defined\n\ntest_target.py:5: NameError")
NAME_ERROR_IN_TARGET = "E       NameError: name 'helper' is not defined\n\ntarget.py:3: NameError"
REAL_FAILURE = ">       return sum(n) / len(n)\nE       ZeroDivisionError: division by zero\n\ntarget.py:2: ZeroDivisionError"


def test_missing_import_in_a_test_is_a_test_bug_not_a_defect():
    assert is_test_infrastructure_bug(NAME_ERROR_IN_TEST)          # was False: "target.py" is inside "test_target.py"
    assert is_test_infrastructure_bug("NameError: name 'pytest' is not defined")
    assert is_test_infrastructure_bug("E   ModuleNotFoundError: No module named 'numpy'\ntest_target.py:1: in <module>")


def test_real_defects_still_count():
    assert not is_test_infrastructure_bug(REAL_FAILURE)
    assert not is_test_infrastructure_bug(NAME_ERROR_IN_TARGET)    # a NameError raised by the reviewed code is a defect
    assert not is_test_infrastructure_bug("E   AssertionError: assert 0 == 3")


def test_broken_test_does_not_confirm_a_finding():
    results = [{"name": "test_f1_a", "finding_id": "f1", "status": "failed", "message": NAME_ERROR_IN_TEST},
               {"name": "test_f2_b", "finding_id": "f2", "status": "failed", "message": REAL_FAILURE}]
    assert failing_tests_by_finding(results) == {"f2": ["test_f2_b"]}


def test_broken_test_does_not_block_a_correct_fix():
    def row(name, status, msg=""):
        return {"name": name, "status": status, "finding_id": "f1", "message": msg}
    before = [row("test_f1_a", "failed", NAME_ERROR_IN_TEST), row("test_f1_b", "failed", REAL_FAILURE)]
    after = [row("test_f1_a", "failed", NAME_ERROR_IN_TEST), row("test_f1_b", "passed")]
    ev = evaluate_fix(before, after, [{"id": "f1", "severity": "high"}])
    assert ev["verified"] and ev["still_failing"] == [] and ev["ignored_broken_tests"] == ["test_f1_a"]


# ------------------------------------------------------------------ generated-test validation

T = "def average(n):\n    return 1\n"


@pytest.mark.parametrize("name,code,expected", [
    ("good", "import pytest\nimport target\n\ndef test_f1_empty():\n    with pytest.raises(ValueError):\n        target.average([])\n", None),
    ("helper asserts", "import target\n\ndef check(x):\n    assert x == 1\n\ndef test_f1_a():\n    check(target.average([1]))\n", None),
    ("class based", "import target\n\nclass TestA:\n    def test_f1_a(self):\n        assert target.average([1]) == 1\n", None),
    ("forgot import pytest", "import target\n\ndef test_f1_e():\n    with pytest.raises(ValueError):\n        target.average([])\n", "import pytest"),
    ("no assertion", "import target\n\ndef test_f1_e():\n    target.average([1])\n", "no assertion"),
    ("unlinked name", "import target\n\ndef test_empty():\n    assert target.average([1]) == 1\n", "must be named"),
    ("unknown finding", "import target\n\ndef test_f9_e():\n    assert target.average([1]) == 1\n", "unknown finding"),
    ("hallucinated function", "import target\n\ndef test_f1_e():\n    assert target.mean([1]) == 1\n", "does not exist"),
])
def test_generated_test_validation(name, code, expected):
    err = validate_test_structure(code, T, "python", {"f1"})
    assert (err is None) if expected is None else (err is not None and expected in err), (name, err)


# ------------------------------------------------------------------ pipeline resilience

def _fake(monkeypatch, handler):
    async def _c(system, user):
        out = handler(system, user)
        if isinstance(out, Exception):
            raise out
        return (out if isinstance(out, str) else json.dumps(out)), 10, 5
    monkeypatch.setattr("app.agent.llm._complete", _c)


async def test_llm_returning_a_list_does_not_crash_the_review(monkeypatch):
    _fake(monkeypatch, lambda s, u: [{"line": 2}])          # valid JSON, wrong shape
    res = await run_review(BUGGY, "llm_only", "python", False)
    assert res["findings"] == [] and any("review failed" in w.lower() or "LLM" in w for w in res["warnings"])


async def test_findings_null_does_not_crash_the_review(monkeypatch):
    _fake(monkeypatch, lambda s, u: {"summary": "x", "findings": None})
    res = await run_review(BUGGY, "llm_only", "python", False)
    assert res["findings"] == [] and any("list of findings" in w for w in res["warnings"])


async def test_bad_fix_reply_keeps_the_confirmed_review(monkeypatch):
    tests = {"test_code": GOOD_TESTS}

    def handler(system, user):
        if "senior code reviewer" in system:
            return REVIEW
        if "write pytest" in system:
            return tests
        return ["not", "an", "object"]                       # the fix step gets nonsense
    _fake(monkeypatch, handler)
    res = await run_review(BUGGY, "full", "python", True)
    assert res["findings"][0]["verdict"] == "confirmed"      # the review survives
    assert res["fix"]["attempted"] is True and "failed" in res["fix"]["reason"].lower()


async def test_unexpected_node_crash_becomes_a_warning(monkeypatch):
    _fake(monkeypatch, lambda s, u: REVIEW if "senior" in s else {"test_code": GOOD_TESTS})

    def boom(*a, **k):
        raise RuntimeError("sandbox exploded")
    monkeypatch.setattr("app.agent.nodes.test_run.run_tests", boom)
    res = await run_review(BUGGY, "full", "python", False)
    assert res["findings"] and any("test_run failed" in w for w in res["warnings"])


async def test_llm_error_during_test_generation_is_retried(monkeypatch):
    calls = {"n": 0}

    def handler(system, user):
        if "senior code reviewer" in system:
            return REVIEW
        calls["n"] += 1
        return RuntimeError("provider hiccup") if calls["n"] == 1 else {"test_code": GOOD_TESTS}
    _fake(monkeypatch, handler)
    res = await run_review(BUGGY, "full", "python", False)
    assert calls["n"] == 2 and res["test_stats"]["attempts"] == 2
    assert res["findings"][0]["verdict"] == "confirmed"


async def test_persistent_llm_error_gives_up_after_the_attempt_limit(monkeypatch):
    calls = {"n": 0}

    def handler(system, user):
        if "senior code reviewer" in system:
            return REVIEW
        calls["n"] += 1
        return RuntimeError("provider down")
    _fake(monkeypatch, handler)
    res = await run_review(BUGGY, "full", "python", False)
    assert calls["n"] == settings.max_test_attempts and res["tests"] == []
    assert any("Test generation failed" in w for w in res["warnings"])


async def test_rejected_tests_are_not_reported_as_never_generated(monkeypatch):
    no_assert = "import target\n\ndef test_f1_empty():\n    target.average([])\n"
    _fake(monkeypatch, lambda s, u: REVIEW if "senior" in s else {"test_code": no_assert})
    res = await run_review(BUGGY, "full", "python", False)
    f = res["findings"][0]
    assert f["verdict"] == "suspected" and "rejected as invalid" in f["verdict_reason"]


async def test_test_without_assertions_is_rejected_then_retried(install_llm):
    no_assert = "import target\n\ndef test_f1_empty():\n    target.average([])\n"
    fake = install_llm(review=REVIEW, tests=[no_assert, GOOD_TESTS], fix=FIXED)
    res = await run_review(BUGGY, "full", "python", False)
    assert res["test_stats"]["invalid_structure"] == 1 and fake.calls.count("tests") == 2


# ------------------------------------------------------------------ LLM client

class _Resp:
    class _Msg:
        content = '{"ok": true}'
    choices = [types.SimpleNamespace(message=_Msg())]
    usage = None


def _client(error_factory):
    state = {"calls": 0}

    class Completions:
        async def create(self, **kw):
            state["calls"] += 1
            err = error_factory(state["calls"], kw)
            if err:
                raise err
            return _Resp()
    return types.SimpleNamespace(chat=types.SimpleNamespace(completions=Completions())), state


class RateLimited(Exception):
    status_code = 429


async def test_rate_limit_is_not_retried_blindly(monkeypatch):
    client, state = _client(lambda n, kw: RateLimited("slow down"))
    monkeypatch.setattr(llm, "get_client", lambda p=None: client)
    monkeypatch.setattr(settings, "llm_provider", "groq")
    with pytest.raises(RuntimeError, match="Rate limit"):
        await llm._complete("s", "u")
    assert state["calls"] == 1                              # was 2: every error was retried without JSON mode


async def test_unsupported_json_mode_falls_back_once(monkeypatch):
    client, state = _client(lambda n, kw: Exception("Unsupported parameter: response_format") if n == 1 else None)
    monkeypatch.setattr(llm, "get_client", lambda p=None: client)
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    text, _, _ = await llm._complete("s", "u")
    assert state["calls"] == 2 and json.loads(text) == {"ok": True}


async def test_non_object_reply_is_retried_then_accepted(monkeypatch):
    replies = iter(["[1, 2, 3]", '{"fine": 1}'])

    async def _c(system, user):
        return next(replies), 1, 1
    monkeypatch.setattr("app.agent.llm._complete", _c)
    assert await llm.complete_json("s", "u") == {"fine": 1}


def test_error_classification_uses_status_not_stray_digits():
    assert "Authentication" not in llm._format_provider_error("groq", Exception("Error code: 400 - 4012 tokens, max 4000"))
    assert "Authentication" in llm._format_provider_error("groq", Exception("Error code: 401 - invalid key"))
    assert "Model" in llm._format_provider_error("groq", Exception("Error code: 404 - model does not exist"))


def test_missing_api_key_names_the_right_setting(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "")
    llm._clients.clear()
    with pytest.raises(ValueError, match="GROQ_API_KEY"):    # was: "set the OPENAI_API_KEY environment variable"
        llm.get_client("groq")
    assert "GROQ_API_KEY" in llm._format_provider_error("groq", ValueError("GROQ_API_KEY is not set."))


def test_set_model_overrides_provider_specific_variable(monkeypatch):
    monkeypatch.setattr(settings, "ollama_model", "stale-model-from-env")
    llm.set_model("ollama", "qwen2.5-coder:7b")
    assert llm.model_name() == "qwen2.5-coder:7b"            # evaluation used to silently run the stale model


def test_clients_are_closed_on_shutdown():
    closed = []

    class C:
        async def close(self):
            closed.append(1)
    llm._clients["x"] = C()
    asyncio.run(llm.close_clients())
    assert closed == [1] and not llm._clients


# ------------------------------------------------------------------ configuration

def test_sandbox_mode_typo_is_rejected_not_silently_unsandboxed():
    assert Settings(_env_file=None, sandbox_mode="Docker").sandbox_mode == "docker"
    with pytest.raises(ValidationError):
        Settings(_env_file=None, sandbox_mode="dokcer")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_provider="gorq")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, per_test_timeout=40, sandbox_timeout=30)


# ------------------------------------------------------------------ sandbox

def test_docker_mode_collects_tests_inside_docker_not_on_the_host(monkeypatch):
    seen = []

    def fake_run(cmd, cwd, timeout, **kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(runner, "_run_capture", fake_run)
    monkeypatch.setattr(settings, "sandbox_mode", "docker")
    assert runner.collect_error(BUGGY, GOOD_TESTS, "python") is None
    cmd = seen[0]
    assert cmd[0] == "docker" and "--network" in cmd and "none" in cmd and "--collect-only" in cmd
    assert sys.executable not in cmd                          # was: pytest ran on the host with the submitted code


def _process_running(args_line: str) -> bool:
    """True if a process with exactly this argument line exists. (pgrep -f would also match any shell whose command
    line merely contains the text, which made an earlier version of this test fail for the wrong reason.)"""
    out = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True).stdout
    return any(line.strip() == args_line for line in out.splitlines())


@pytest.mark.skipif(os.name != "posix" or shutil.which("ps") is None, reason="needs POSIX and ps")
def test_timeout_kills_child_processes_too(monkeypatch):
    monkeypatch.setattr(settings, "sandbox_timeout", 2)
    duration = f"47.{os.getpid()}"                        # unique to this run, so nothing else can match it
    code = f"import subprocess\nsubprocess.Popen(['sleep', '{duration}'])\nimport time\ntime.sleep(30)\n"
    res = runner.run_tests(code, "import target\n\ndef test_f1_x():\n    assert True\n")
    assert res[0]["status"] == "timeout"
    deadline = time.time() + 3                            # SIGKILL is asynchronous
    while time.time() < deadline and _process_running(f"sleep {duration}"):
        time.sleep(0.1)
    assert not _process_running(f"sleep {duration}")


@pytest.mark.skipif(shutil.which(settings.node_binary) is None, reason="Node.js not installed")
def test_javascript_classes_are_exported_to_tests():
    code = "class Counter {\n  constructor() { this.n = 0; }\n  inc() { this.n += 1; return this.n; }\n}\n"
    tests = ("const test = require('node:test');\nconst assert = require('node:assert');\n"
             "const target = require('./target.js');\n"
             "test('test_f1_normal_inc', { timeout: 3000 }, () => { assert.strictEqual(new target.Counter().inc(), 1); });\n")
    assert runner.run_tests(code, tests, "javascript")[0]["status"] == "passed"


# ------------------------------------------------------------------ static analysis

def test_failing_analyzer_is_reported_not_treated_as_clean(monkeypatch):
    from app.tools import analyzers

    def boom(*a, **k):
        raise FileNotFoundError("bandit missing")
    monkeypatch.setattr(analyzers.subprocess, "run", boom)
    errors = []
    assert analyzers.analyze("eval(x)", "python", errors) == []
    assert any("bandit" in e for e in errors) and any("ruff" in e for e in errors)


async def test_static_analyzer_failure_becomes_a_warning(monkeypatch):
    from app.tools import analyzers
    monkeypatch.setattr(analyzers.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("x")))
    _fake(monkeypatch, lambda s, u: REVIEW)
    res = await run_review(BUGGY, "llm_static", "python", False)
    assert any("Static analyzer problem" in w for w in res["warnings"])


async def test_hung_mcp_server_falls_back_to_direct_tools(monkeypatch):
    async def hang(*a, **k):
        await asyncio.sleep(30)
    monkeypatch.setattr("app.agent.nodes.static_analysis.call_tool", hang)
    monkeypatch.setattr(settings, "use_mcp", True)
    monkeypatch.setattr(settings, "mcp_timeout", 0.2)
    res = await run_review("def run(x):\n    return eval(x)\n", "static_only", "python", False)
    assert res["findings"] and any("MCP server unavailable" in w and "TimeoutError" in w for w in res["warnings"])


# ------------------------------------------------------------------ storage

def test_sqlite_connections_are_closed(monkeypatch):
    opened = []
    real = sqlite3.connect

    def tracking(*a, **k):
        con = real(*a, **k)
        opened.append(con)
        return con
    monkeypatch.setattr(storage.sqlite3, "connect", tracking)
    storage.history("x")
    storage.save_review("x.py", {"language": "python", "mode": "full", "quality_score": 90})
    storage.last_review("x.py")
    storage.stats()
    assert len(opened) == 4
    for con in opened:
        with pytest.raises(sqlite3.ProgrammingError):         # "Cannot operate on a closed database"
            con.execute("select 1")


def test_regression_keeps_findings_sharing_a_line_distinct():
    f = lambda i, t: {"id": i, "title": t, "snippet": "return a / b", "severity": "high"}  # noqa: E731
    c = storage.compare({"findings": [f("f1", "A"), f("f2", "B")], "quality_score": 80},
                        {"findings": [f("f1", "A")], "quality_score": 88}, 1, "t")
    assert len(c["fixed"]) == 1 and len(c["persisting"]) == 1 and c["new"] == []


def test_history_pagination():
    for _ in range(5):
        storage.save_review("p.py", {"language": "python", "mode": "full", "quality_score": 1})
    assert len(storage.history("p.py", 2)) == 2
    assert [r["id"] for r in storage.history("p.py", 2, 2)] == [3, 2]


# ------------------------------------------------------------------ RAG

class FakeCollection:
    def __init__(self):
        self.docs, self.upserts, self.deleted = {}, [], []

    def get(self, include=None):
        return {"ids": list(self.docs), "metadatas": [self.docs[i][1] for i in self.docs]}

    def upsert(self, ids, documents, metadatas):
        self.upserts.append(list(ids))
        for i, d, m in zip(ids, documents, metadatas, strict=True):
            self.docs[i] = (d, m)

    def delete(self, ids):
        self.deleted += ids
        for i in ids:
            self.docs.pop(i, None)

    def count(self):
        return len(self.docs)


def test_rag_index_updates_only_what_changed(tmp_path, monkeypatch):
    from app.rag import store
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "a.md").write_text("# A\n\n## one\n" + "alpha " * 20 + "\n\n## two\n" + "beta " * 20)
    (kb / "b.md").write_text("# B\n\n## only\n" + "gamma " * 20)
    monkeypatch.setattr(settings, "knowledge_dir", str(kb))
    coll = FakeCollection()
    monkeypatch.setattr(store, "_collection", lambda: coll)

    assert store.index_knowledge() == 3
    assert store.index_knowledge() == 3 and len(coll.upserts) == 1      # unchanged: nothing re-embedded
    (kb / "a.md").write_text("# A\n\n## one\n" + "alpha " * 20 + "\n\n## two\n" + "CHANGED " * 20)
    store.index_knowledge()
    assert coll.upserts[-1] == ["a-2"]                                  # only the edited chunk (was: never updated)
    (kb / "b.md").unlink()
    store.index_knowledge()
    assert coll.deleted == ["b-1"] and coll.count() == 2


def test_rag_client_is_created_once(tmp_path, monkeypatch):
    from app.rag import store
    created = []

    class FakeClient:
        def __init__(self, path):
            created.append(path)

        def get_or_create_collection(self, name):
            return FakeCollection()
    monkeypatch.setitem(sys.modules, "chromadb", types.SimpleNamespace(PersistentClient=FakeClient))
    monkeypatch.setattr(settings, "chroma_dir", str(tmp_path / "chroma"))
    store.reset_cache()
    store._collection()
    store._collection()
    store._collection()
    store.reset_cache()
    assert len(created) == 1                                            # was one new client per query


# ------------------------------------------------------------------ API

def test_api_error_handling_and_health(install_llm, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:
        assert c.get("/health").json()["sandbox_isolated"] is False

        async def explode(*a, **k):
            raise RuntimeError("graph exploded")
        monkeypatch.setattr("app.main.run_review", explode)
        r = c.post("/review", json={"code": BUGGY})
        assert r.status_code == 500 and "graph exploded" in r.json()["detail"]
        monkeypatch.undo()

        assert c.get("/history", params={"file_name": "x", "limit": 0}).status_code == 422


def test_review_survives_a_history_database_failure(install_llm, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    install_llm(review=REVIEW)
    monkeypatch.setattr("app.main.storage.log_run", lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("locked")))
    with TestClient(app) as c:
        r = c.post("/review", json={"code": BUGGY, "mode": "llm_only"})
        assert r.status_code == 200 and r.json()["findings"]
        assert any("history could not be saved" in w.lower() for w in r.json()["warnings"])


def test_unused_path_import_guard():
    assert Path(__file__).exists()
