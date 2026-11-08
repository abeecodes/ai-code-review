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
    hang = "import time, target\n\ndef test_f1_boundary_hang():\n    time.sleep(30)\n"
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
