"""Deterministic scoring helpers shared by the aggregate node and the fix verifier."""

ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
# Points deducted per finding. Fixed weights make the score reproducible and easy to explain.
PENALTY = {"critical": 20, "high": 12, "medium": 6, "low": 2, "info": 0}


def score_breakdown(findings: list) -> tuple:
    counts = {s: 0 for s in PENALTY}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    score = max(0, 100 - sum(counts[s] * PENALTY[s] for s in PENALTY))
    return score, counts


# Errors that mean the GENERATED TEST is broken, not that the reviewed code is wrong.
TEST_BUG_MARKERS = ("NameError", "ImportError", "ModuleNotFoundError", "SyntaxError", "AttributeError: module 'target'")


def failing_tests_by_finding(results: list) -> dict:
    """finding id -> names of its tests that failed or crashed on the code.
    Tests broken by their own mistakes (missing import, wrong name) are excluded: they prove nothing."""
    out = {}
    for r in results:
        if not r.get("finding_id") or r["status"] not in ("failed", "error"):
            continue
        if any(marker in r.get("message", "") for marker in TEST_BUG_MARKERS):
            continue
        out.setdefault(r["finding_id"], []).append(r["name"])
    return out
