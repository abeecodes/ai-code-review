"""Deterministic scoring helpers shared by the aggregate node and the fix verifier."""
import re

ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
# Points deducted per finding. Fixed weights make the score reproducible and easy to explain.
PENALTY = {"critical": 20, "high": 12, "medium": 6, "low": 2, "info": 0}


def score_breakdown(findings: list) -> tuple:
    counts = {s: 0 for s in PENALTY}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    score = max(0, 100 - sum(counts[s] * PENALTY[s] for s in PENALTY))
    return score, counts


# Failures that say "the generated TEST (or the environment) is broken", not "the reviewed code is wrong".
_ALWAYS_TEST_PROBLEM = ("ImportError", "ModuleNotFoundError", "SyntaxError", "IndentationError")
_DEPENDS_ON_LOCATION = ("NameError", "UnboundLocalError")
_LOCATION = re.compile(r"([\w./\\:-]+\.py):(\d+):")


def is_test_infrastructure_bug(message: str) -> bool:
    """True if a failure was caused by a broken generated test rather than by a defect in the target.

    A NameError is a real defect only when it is raised inside target.py. pytest prints the frame that raised
    the exception last, so the last '<file>.py:<line>:' reference in the message tells us where it happened.
    (Do not test `"target.py" in message`: it is a substring of "test_target.py".)
    """
    if not message:
        return False
    if "AttributeError: module 'target'" in message or "AttributeError: <module 'target'" in message:
        return True  # the test called a function that does not exist
    if re.search(r"fixture '[^']+' not found", message):
        return True
    if any(re.search(rf"\b{e}\b", message) for e in _ALWAYS_TEST_PROBLEM):
        return True
    if any(re.search(rf"\b{e}\b", message) for e in _DEPENDS_ON_LOCATION):
        locations = _LOCATION.findall(message)
        if not locations:
            return True  # raised while loading or running the test file itself
        return re.split(r"[\\/]", locations[-1][0])[-1] != "target.py"
    return False


def failing_tests_by_finding(results: list) -> dict:
    """finding id -> names of its tests that failed or crashed on the code.
    Tests broken by their own mistakes (missing import, hallucinated function) are excluded: they prove nothing."""
    out = {}
    for r in results:
        if not r.get("finding_id") or r["status"] not in ("failed", "error"):
            continue
        if is_test_infrastructure_bug(r.get("message", "")):
            continue
        out.setdefault(r["finding_id"], []).append(r["name"])
    return out


def is_testable(finding: dict) -> bool:
    """Behavioural findings get generated tests. Only pure style/maintainability findings are excluded,
    because the LLM often mislabels real correctness bugs as 'performance'."""
    return finding.get("severity") != "info" and finding.get("category") != "maintainability"
