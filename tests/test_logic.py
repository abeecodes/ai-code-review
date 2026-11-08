import pytest
from app.agent.modes import detect_language
from app.fix_logic import evaluate_fix
from app.report import to_markdown
from app import storage
from eval import metrics


def T(name, status, fid="f1"):
    return {"name": name, "status": status, "finding_id": fid, "category": "normal", "message": ""}


FINDINGS = [{"id": "f1", "severity": "medium"}, {"id": "f2", "severity": "high"}]


def test_fix_verified_only_when_all_checks_hold():
    before = [T("a", "failed"), T("b", "passed"), T("c", "failed", "f2")]
    ok = evaluate_fix(before, [T("a", "passed"), T("b", "passed"), T("c", "passed", "f2")], FINDINGS)
    assert ok["verified"] and ok["score_before"] == 82 and ok["score_after"] == 100
    partial = evaluate_fix(before, [T("a", "passed"), T("b", "passed"), T("c", "failed", "f2")], FINDINGS)
    assert not partial["verified"] and partial["still_failing"] == ["c"] and partial["resolved_findings"] == ["f1"]
    assert partial["score_after"] == 88
    regress = evaluate_fix(before, [T("a", "passed"), T("b", "failed"), T("c", "passed", "f2")], FINDINGS)
    assert not regress["verified"] and regress["regressions"] == ["b"]
    nothing = evaluate_fix([T("b", "passed")], [T("b", "passed")], FINDINGS)
    assert not nothing["verified"]  # nothing was actually fixed


def test_language_detection():
    assert detect_language("def f(x):\n    return x\n") == "python"
    assert detect_language("const a = (x) => x;\nconsole.log(a(1));") == "javascript"


def test_line_matching_rules():
    defects = [{"id": "d", "category": "boundary", "line": 10}]
    findings = [{"line": 11, "severity": "high"}, {"line": 10, "severity": "low"}, {"line": 40, "severity": "medium"},
                {"line": 12, "severity": "info"}, {"line": None, "severity": "high"}]
    m = metrics.match_findings(findings, defects, tol=2)
    assert len(m["tp"]) == 1 and m["tp"][0][0]["line"] == 10  # the closest finding wins
    assert m["dup"] == 1 and len(m["fp"]) == 2 and m["fn"] == []  # info ignored; no-line finding is a FP
    assert metrics.match_findings([], defects)["fn"] == defects
    assert metrics.prf(8, 2, 2)["f1"] == pytest.approx(0.8)


def test_summary_over_repeated_runs():
    truth = {"bug.py": {"clean": False, "defects": [{"id": "x", "category": "injection", "line": 3}]},
             "ok.py": {"clean": True, "defects": []}}

    def rec(file, run, findings):
        return {"model": "m", "mode": "full", "file": file, "run": run, "findings": findings, "usage": {},
                "test_stats": {}, "test_coverage": {}, "seconds": 1.0}

    hit = [{"line": 3, "severity": "high", "verdict": "confirmed"}]
    recs = [rec("bug.py", 1, hit), rec("ok.py", 1, []), rec("bug.py", 2, []), rec("ok.py", 2, hit)]
    s = metrics.summarise(recs, truth)
    assert s["runs"] == 2 and abs(s["recall"] - 0.5) < 1e-9 and s["recall_std"] > 0
    assert s["clean_fp_files"] == 0.5 and s["by_category"]["injection"]["recall"] == 0.5


def test_regression_compare_and_markdown(tmp_path):
    old = {"quality_score": 70, "findings": [
        {"id": "f1", "title": "A", "snippet": "x = eval(y)", "severity": "high"},
        {"id": "f2", "title": "B", "snippet": "return a / b", "severity": "medium"}]}
    new = {"quality_score": 94, "findings": [
        {"id": "f1", "title": "B again", "snippet": "return  a / b", "severity": "medium"},
        {"id": "f2", "title": "C", "snippet": "open(p)", "severity": "low"}]}
    c = storage.compare(old, new, 1, "t")
    assert [f["snippet"] for f in c["fixed"]] == ["x = eval(y)"]
    assert [f["snippet"] for f in c["new"]] == ["open(p)"] and len(c["persisting"]) == 1
    md = to_markdown({"language": "python", "mode": "full", "quality_score": 94, "score_breakdown": {}, "summary": "s",
                      "findings": [{"id": "f1", "severity": "high", "verdict": "confirmed", "line": 2, "title": "T",
                                    "category": "bug", "source": "llm", "snippet": "x", "explanation": "e",
                                    "failure_scenario": "", "fix": ""}], "tests": [], "regression": c,
                      "warnings": [], "timings": {}, "usage": {}})
    assert "🔴 confirmed" in md and "Changes since last review" in md
