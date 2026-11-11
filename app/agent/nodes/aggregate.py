from app.agent.nodes.common import timed
from app.schemas import ReviewResponse
from app.scoring import ORDER, failing_tests_by_finding, is_testable, score_breakdown


@timed("aggregate", fail_soft=False)
async def aggregate_node(state):
    findings = [dict(f) for f in state.get("findings", [])]
    tests = state.get("test_results", [])

    failing = failing_tests_by_finding(tests)
    ran = {}
    for t in tests:
        if t.get("finding_id") and t["name"] != "sandbox":
            ran.setdefault(t["finding_id"], []).append(t["status"])

    sandbox_rows = [t for t in tests if t["name"] == "sandbox"]
    for f in findings:
        if f["id"] in failing:
            f["verdict"] = "confirmed"
            f["verdict_reason"] = "a generated test failed or crashed on the code"
        elif not is_testable(f):
            f["verdict"] = "suspected"
            f["verdict_reason"] = "not tested: this is a style or maintainability finding, not a behaviour"
        elif sandbox_rows and f["id"] not in ran:
            f["verdict"] = "suspected"
            f["verdict_reason"] = f"tests could not run: {sandbox_rows[0]['message'][:120]}"
        elif f["id"] in ran:
            f["verdict"] = "suspected"
            if set(ran[f["id"]]) == {"timeout"}:
                f["verdict_reason"] = "tests timed out, so the result is inconclusive"
            else:
                f["verdict_reason"] = "generated tests passed on the code, so the defect was not reproduced"
        elif state.get("test_stats", {}).get("attempts") and not tests:
            f["verdict"] = "suspected"
            f["verdict_reason"] = (f"generated tests were rejected as invalid after "
                                   f"{state['test_stats']['attempts']} attempt(s), so none could be run")
        else:
            f["verdict"] = "suspected"
            f["verdict_reason"] = "no test was generated for this finding"

    findings.sort(key=lambda f: (ORDER.get(f["severity"], 5), f.get("line") or 0))
    score, breakdown = score_breakdown(findings)

    real = [t for t in tests if t["name"] != "sandbox"]
    coverage = {}
    for t in real:
        coverage[t["category"]] = coverage.get(t["category"], 0) + 1
    stats = dict(state.get("test_stats") or {})
    if stats.get("attempts"):
        stats["unlinked"] = sum(1 for t in real if not t.get("finding_id"))
        stats["ran"] = len(real)

    counts = {}
    for s in state.get("static_findings", []):
        counts[s["source"]] = counts.get(s["source"], 0) + 1

    result = ReviewResponse(
        summary=state.get("summary", ""), quality_score=score, score_breakdown=breakdown,
        language=state.get("language", "python"), mode=state.get("mode", "full"),
        findings=findings, tests=tests, test_code=state.get("test_code", ""),
        test_stats=stats, test_coverage=coverage, fix=state.get("fix"),
        static_counts=counts, rag_sources=sorted({c["source"] for c in state.get("rag_context", [])}),
        timings=state.get("timings", {}), warnings=state.get("warnings", []),
    )
    return {"result": result.model_dump()}