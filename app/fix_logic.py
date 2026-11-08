"""Fix verification: compare test outcomes before and after the proposed fix."""
from app.scoring import failing_tests_by_finding, score_breakdown

_BAD = ("failed", "error")


def _tests(results: list) -> dict:
    return {r["name"]: r["status"] for r in results if r["name"] != "sandbox"}


def _counts(results: list) -> dict:
    c = {"passed": 0, "failed": 0, "error": 0, "timeout": 0}
    for status in _tests(results).values():
        c[status] += 1
    return c


def evaluate_fix(before: list, after: list, findings: list) -> dict:
    """A fix is VERIFIED only if at least one failing test now passes, none of the originally failing
    tests still fails, and no test that used to pass has broken."""
    b, a = _tests(before), _tests(after)
    fixed = [n for n, s in b.items() if s in _BAD and a.get(n) == "passed"]
    still = [n for n, s in b.items() if s in _BAD and a.get(n) != "passed"]
    regress = [n for n, s in b.items() if s == "passed" and a.get(n) != "passed"]

    resolved = [fid for fid, names in failing_tests_by_finding(before).items()
                if all(a.get(n) == "passed" for n in names)]
    score_before, _ = score_breakdown(findings)
    score_after, _ = score_breakdown([f for f in findings if f["id"] not in resolved])
    return {"verified": bool(fixed) and not still and not regress, "fixed_tests": fixed, "still_failing": still,
            "regressions": regress, "resolved_findings": resolved, "before": _counts(before),
            "after": _counts(after), "score_before": score_before, "score_after": score_after}
