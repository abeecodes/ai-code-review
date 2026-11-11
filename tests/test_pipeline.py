import json

from app.agent.graph import run_review
from app.agent.llm import complete_json
from app.core.config import settings
from tests.conftest import BUGGY, FIXED, GOOD_TESTS, REVIEW


async def test_full_pipeline_confirms_defect_and_verifies_fix(install_llm):
    fake = install_llm(review=REVIEW, tests=[GOOD_TESTS], fix=FIXED)
    res = await run_review(BUGGY, "full", "python", True)

    f = res["findings"][0]
    assert f["verdict"] == "confirmed" and f["snippet"] == "return sum(numbers) / len(numbers)"
    assert res["quality_score"] == 94
    assert res["test_coverage"] == {"normal": 1, "empty": 1}

    fix = res["fix"]
    assert fix["verified"] is True and fix["fixed_tests"] == ["test_f1_empty_list_raises_value_error"]
    assert fix["regressions"] == [] and fix["still_failing"] == []
    assert fix["score_before"] == 94 and fix["score_after"] == 100
    assert fake.calls == ["review", "tests", "fix"]
    assert res["usage"]["llm_calls"] == 3 and res["usage"]["input_tokens"] == 300


async def test_fix_that_breaks_a_passing_test_is_not_verified(install_llm):
    broken = "def average(numbers):\n    if not numbers:\n        raise ValueError('empty')\n    return 0\n"
    install_llm(review=REVIEW, tests=[GOOD_TESTS], fix=broken)
    res = await run_review(BUGGY, "full", "python", True)
    assert res["fix"]["verified"] is False
    assert res["fix"]["regressions"] == ["test_f1_normal_average"]


async def test_retry_when_generated_tests_have_a_syntax_error(install_llm):
    fake = install_llm(review=REVIEW, tests=["def test_f1_x(:\n  pass", GOOD_TESTS], fix=FIXED)
    res = await run_review(BUGGY, "full", "python", False)
    st = res["test_stats"]
    assert st["attempts"] == 2 and st["retries"] == 1 and st["syntax_errors"] == 1
    assert st["discarded_unparseable"] == 1
    assert res["findings"][0]["verdict"] == "confirmed" and fake.calls.count("tests") == 2


async def test_retry_when_a_test_hangs(install_llm, monkeypatch):
    monkeypatch.setattr(settings, "per_test_timeout", 1)
    hang = "import time, target\n\ndef test_f1_boundary_hang():\n    time.sleep(30)\n    assert target.average([1]) == 1\n"
    install_llm(review=REVIEW, tests=[hang, GOOD_TESTS])
    res = await run_review(BUGGY, "full", "python", False)
    assert res["test_stats"]["timeouts"] == 1 and res["test_stats"]["retries"] == 1
    assert {t["status"] for t in res["tests"]} == {"passed", "failed"}


async def test_forbidden_calls_are_rejected_then_retried(install_llm):
    evil = "import subprocess, target\n\ndef test_f1_malicious_x():\n    pass\n"
    install_llm(review=REVIEW, tests=[evil, GOOD_TESTS])
    res = await run_review(BUGGY, "full", "python", False)
    assert res["test_stats"]["blocked"] == 1 and res["test_stats"]["retries"] == 1


async def test_static_only_makes_no_llm_calls(install_llm):
    fake = install_llm()
    res = await run_review("def run(x):\n    return eval(x)\n", "static_only", "python", True)
    assert fake.calls == [] and res["usage"]["llm_calls"] == 0
    assert any("eval" in f["explanation"].lower() or "exec" in f["explanation"].lower() for f in res["findings"])
    assert res["tests"] == [] and res["fix"] is None


async def test_llm_only_skips_tools_rag_tests(install_llm):
    install_llm(review=REVIEW)
    res = await run_review(BUGGY, "llm_only", "python", True)
    assert res["static_counts"] == {} and res["rag_sources"] == [] and res["tests"] == []


async def test_no_confirmed_defect_means_no_fix_attempt(install_llm):
    passing = "import target\n\ndef test_f1_normal_average():\n    assert target.average([2, 4]) == 3\n"
    install_llm(review=REVIEW, tests=[passing])
    res = await run_review(BUGGY, "full", "python", True)
    assert res["findings"][0]["verdict"] == "suspected"
    assert res["fix"]["attempted"] is False


async def test_response_cache_serves_identical_prompts(install_llm, monkeypatch):
    monkeypatch.setattr(settings, "llm_cache", True)
    fake = install_llm(review=REVIEW)
    from app.agent.llm import new_usage
    usage = new_usage()
    a = await complete_json("senior code reviewer", "same prompt")
    b = await complete_json("senior code reviewer", "same prompt")
    assert a == b == json.loads(json.dumps(REVIEW)) and fake.calls == ["review"]
    assert usage["llm_calls"] == 1 and usage["cache_hits"] == 1


# ---------------------------------------------------------------------------
# Priority 1 Regression Tests: Real Collection Check & Execution Pipeline
# ---------------------------------------------------------------------------
import tempfile
from pathlib import Path
from app.sandbox.runner import collect_error


def test_real_collect_error_succeeds_on_valid_code():
    """Verify collect_error succeeds (returns None) on valid code and test suite."""
    err = collect_error(BUGGY, GOOD_TESTS, "python")
    assert err is None


def test_real_collect_error_detects_unimportable_module():
    """Verify collect_error catches tests importing nonexistent modules."""
    bad_import = "import pytest, nonexistent_module_xyz_123\n\ndef test_f1():\n    assert True\n"
    err = collect_error(BUGGY, bad_import, "python")
    assert err is not None
    assert "nonexistent_module_xyz_123" in err


def test_real_collect_error_skips_javascript():
    """JavaScript tests do not use pytest collect; collect_error returns None immediately."""
    err = collect_error("function f() {}", "test('a', () => {})", "javascript")
    assert err is None


def test_collect_error_cleans_up_temporary_directory(monkeypatch):
    """Verify that temporary files are cleaned up after collection."""
    created_dirs = []
    orig_td = tempfile.TemporaryDirectory

    def tracking_td(*args, **kwargs):
        td = orig_td(*args, **kwargs)
        created_dirs.append(Path(td.name))
        return td

    monkeypatch.setattr(tempfile, "TemporaryDirectory", tracking_td)
    err = collect_error(BUGGY, GOOD_TESTS, "python")
    assert err is None
    assert len(created_dirs) == 1
    assert not created_dirs[0].exists()


async def test_collect_error_argument_forwarding(install_llm, monkeypatch):
    """Verify the exact arguments passed to collect_error() during test_gen."""
    import app.agent.nodes.test_gen as test_gen_mod

    recorded_calls = []
    real_collect = test_gen_mod.collect_error

    def spy_collect_error(code, test_code, language="python"):
        recorded_calls.append({"code": code, "test_code": test_code, "language": language})
        return real_collect(code, test_code, language)

    monkeypatch.setattr(test_gen_mod, "collect_error", spy_collect_error)
    install_llm(review=REVIEW, tests=[GOOD_TESTS])
    res = await run_review(BUGGY, "full", "python", False)

    assert len(recorded_calls) == 1
    call = recorded_calls[0]
    assert call["code"] == BUGGY
    assert call["test_code"] == GOOD_TESTS.strip()
    assert call["language"] == "python"
    assert res["test_stats"]["attempts"] == 1


async def test_retry_exhaustion_when_both_candidates_fail_collection(install_llm):
    """Verify retry exhaustion when both generated candidates fail collection."""
    candidate1 = "import pytest, target, non_existent_pkg_1\n\ndef test_f1_broken(): pass\n"
    candidate2 = "import pytest, target, non_existent_pkg_2\n\ndef test_f1_broken(): pass\n"
    fake = install_llm(review=REVIEW, tests=[candidate1, candidate2])
    res = await run_review(BUGGY, "full", "python", False)

    st = res["test_stats"]
    assert st["attempts"] == 2
    assert st["retries"] == 1
    assert res["test_code"] == ""
    assert res["tests"] == []
    assert any("fails to load" in w or "discarded after 2 attempts" in w for w in res["warnings"])
    assert all(f.get("verdict") == "suspected" for f in res["findings"])
    assert fake.calls.count("tests") == 2


async def test_successfully_collected_tests_are_executed(install_llm):
    """Verify that successfully collected tests are actually executed and findings robustly matched."""
    fake = install_llm(review=REVIEW, tests=[GOOD_TESTS], fix=FIXED)
    res = await run_review(BUGGY, "full", "python", False)

    assert res["test_code"] == GOOD_TESTS.strip()
    real_tests = [t for t in res["tests"] if t["name"] != "sandbox"]
    assert len(real_tests) == 2

    by_name = {t["name"]: t for t in real_tests}
    assert "test_f1_normal_average" in by_name
    assert by_name["test_f1_normal_average"]["status"] == "passed"
    assert "test_f1_empty_list_raises_value_error" in by_name
    assert by_name["test_f1_empty_list_raises_value_error"]["status"] in ("failed", "error")

    # Robust matching by finding content (not assuming findings[0])
    div0_findings = [f for f in res["findings"] if "division by zero" in f["title"].lower() or "empty" in f["title"].lower()]
    assert len(div0_findings) >= 1
    assert div0_findings[0]["verdict"] == "confirmed"
    assert "failed or crashed" in div0_findings[0]["verdict_reason"]
    assert fake.calls.count("tests") == 1


async def test_retry_when_generated_tests_fail_real_collection_robust(install_llm):
    """End-to-end regression: Candidate 1 fails real collection, Candidate 2 passes and confirms defect."""
    bad_collection = "import pytest, target, non_existent_pkg_404\n\ndef test_f1_broken(): pass\n"
    fake = install_llm(review=REVIEW, tests=[bad_collection, GOOD_TESTS], fix=FIXED)
    res = await run_review(BUGGY, "full", "python", False)

    st = res["test_stats"]
    assert st["attempts"] == 2
    assert st["retries"] == 1
    assert fake.calls.count("tests") == 2

    # Robust finding verification by content
    div0_findings = [f for f in res["findings"] if "zero" in f["title"].lower() or "empty" in f["title"].lower()]
    assert len(div0_findings) >= 1
    assert div0_findings[0]["verdict"] == "confirmed"

