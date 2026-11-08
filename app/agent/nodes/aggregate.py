from app.agent.nodes.common import timed
from app.schemas import ReviewResponse
from app.scoring import ORDER, failing_tests_by_finding, score_breakdown


@timed("aggregate")
async def aggregate_node(state):
    findings = [dict(f) for f in state.get("findings", [])]
    tests = state.get("test_results", [])

    # A failing or crashing correct-behaviour test confirms the defect; otherwise it stays suspected.
    failing = failing_tests_by_finding(tests)
    for f in findings:
        f["verdict"] = "confirmed" if f["id"] in failing else "suspected"

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
