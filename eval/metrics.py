"""Pure metric functions (no LLM, no I/O) so they can be unit-tested."""
import statistics


def match_findings(findings: list, defects: list, tol: int = 2) -> dict:
    """Match findings to labelled defects by LINE (within `tol` lines), one finding per defect.

    tp   : a finding matched a defect
    dup  : an extra finding on an already-matched defect (ignored, not a false positive)
    fp   : a finding that matches no defect (everything reported on a clean file lands here)
    fn   : a defect nobody found
    'info' severity findings are ignored.
    """
    real = [f for f in findings if f.get("severity") != "info"]
    cand = sorted((abs(f["line"] - d["line"]), fi, di)
                  for fi, f in enumerate(real) if f.get("line") is not None
                  for di, d in enumerate(defects) if abs(f["line"] - d["line"]) <= tol)
    used_f, used_d, tp = set(), set(), []
    for _, fi, di in cand:
        if fi not in used_f and di not in used_d:
            used_f.add(fi)
            used_d.add(di)
            tp.append((real[fi], defects[di]))
    near = {fi for _, fi, _ in cand}
    dup = [fi for fi in range(len(real)) if fi not in used_f and fi in near]
    fp = [fi for fi in range(len(real)) if fi not in used_f and fi not in near]
    fn = [defects[di] for di in range(len(defects)) if di not in used_d]
    return {"tp": tp, "fp": [real[i] for i in fp], "fn": fn, "dup": len(dup)}


def prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": p, "recall": r, "f1": f1}


def score_record(rec: dict, truth: dict, tol: int = 2) -> dict:
    m = match_findings(rec["findings"], truth["defects"], tol)
    by_cat = {}
    for d in truth["defects"]:
        by_cat.setdefault(d["category"], {"defects": 0, "found": 0, "confirmed": 0})["defects"] += 1
    for finding, defect in m["tp"]:
        c = by_cat[defect["category"]]
        c["found"] += 1
        c["confirmed"] += finding.get("verdict") == "confirmed"
    return {"tp": len(m["tp"]), "fp": len(m["fp"]), "fn": len(m["fn"]), "dup": m["dup"],
            "confirmed_tp": sum(f.get("verdict") == "confirmed" for f, _ in m["tp"]),
            "clean": truth["clean"], "by_cat": by_cat}


def _mean_std(values: list) -> tuple:
    values = list(values)
    if not values:
        return 0.0, 0.0
    return statistics.mean(values), (statistics.pstdev(values) if len(values) > 1 else 0.0)


def summarise(records: list, truth: dict, tol: int = 2) -> dict:
    """Metrics for ONE (model, mode) group: micro-averaged within each run, mean ± std across runs."""
    ok = [r for r in records if not r.get("error")]
    runs = sorted({r["run"] for r in ok})
    per_run = []
    for run in runs:
        scored = [(r, score_record(r, truth[r["file"]], tol)) for r in ok if r["run"] == run]
        tp, fp, fn = (sum(s[k] for _, s in scored) for k in ("tp", "fp", "fn"))
        clean = [s for _, s in scored if s["clean"]]
        cats = {}
        for _, s in scored:
            for c, v in s["by_cat"].items():
                agg = cats.setdefault(c, {"defects": 0, "found": 0, "confirmed": 0})
                for k in agg:
                    agg[k] += v[k]
        per_run.append({**prf(tp, fp, fn), "tp": tp, "fp": fp, "fn": fn,
                        "confirmed_rate": sum(s["confirmed_tp"] for _, s in scored) / tp if tp else 0.0,
                        "clean_fp_files": sum(s["fp"] > 0 for s in clean) / len(clean) if clean else 0.0,
                        "clean_fp_avg": sum(s["fp"] for s in clean) / len(clean) if clean else 0.0,
                        "cats": cats})
    out = {"runs": len(runs), "records": len(ok), "errors": len(records) - len(ok)}
    for k in ("precision", "recall", "f1", "confirmed_rate", "clean_fp_files", "clean_fp_avg"):
        out[k], out[k + "_std"] = _mean_std(r[k] for r in per_run)
    cat_names = sorted({c for r in per_run for c in r["cats"]})
    out["by_category"] = {}
    for c in cat_names:
        rec = _mean_std(r["cats"][c]["found"] / r["cats"][c]["defects"] for r in per_run if c in r["cats"])
        conf = _mean_std(r["cats"][c]["confirmed"] / r["cats"][c]["found"]
                         for r in per_run if c in r["cats"] and r["cats"][c]["found"])
        out["by_category"][c] = {"defects": per_run[0]["cats"][c]["defects"] if c in per_run[0]["cats"] else 0,
                                 "recall": rec[0], "confirmed": conf[0]}

    n = len(ok) or 1
    out["avg_seconds"] = sum(r["seconds"] for r in ok) / n
    out["avg_input_tokens"] = sum(r["usage"].get("input_tokens", 0) for r in ok) / n
    out["avg_output_tokens"] = sum(r["usage"].get("output_tokens", 0) for r in ok) / n
    out["avg_llm_calls"] = sum(r["usage"].get("llm_calls", 0) for r in ok) / n

    staged = [r for r in ok if r["test_stats"].get("attempts")]
    if staged:
        ts = lambda k: sum(r["test_stats"].get(k, 0) for r in staged)  # noqa: E731
        out["tests"] = {
            "reviews_with_tests": len(staged),
            "retry_rate": sum(r["test_stats"].get("retries", 0) > 0 for r in staged) / len(staged),
            "syntax_error_rate": sum(r["test_stats"].get("syntax_errors", 0) > 0 for r in staged) / len(staged),
            "timeout_rate": sum(r["test_stats"].get("timeouts", 0) > 0 for r in staged) / len(staged),
            "avg_ran": ts("ran") / len(staged), "avg_discarded": (ts("discarded_unparseable") + ts("unlinked")) / len(staged),
            "coverage": {c: sum(r["test_coverage"].get(c, 0) for r in staged) / len(staged)
                         for c in sorted({c for r in staged for c in r["test_coverage"]})},
        }
    fixes = [r["fix"] for r in ok if r.get("fix") and r["fix"].get("attempted")]
    if fixes:
        out["fix"] = {"attempted": len(fixes), "verified_rate": sum(f["verified"] for f in fixes) / len(fixes),
                      "avg_score_before": sum(f["score_before"] for f in fixes) / len(fixes),
                      "avg_score_after": sum(f["score_after"] for f in fixes) / len(fixes)}
    return out
