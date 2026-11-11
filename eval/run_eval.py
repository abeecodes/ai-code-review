"""Evaluate the reviewer on the labelled benchmark.

Examples (from the project root):
  python -m eval.run_eval --modes static_only                       # no LLM needed, seconds
  python -m eval.run_eval --models ollama:qwen2.5-coder:7b --runs 1 --limit 10
  python -m eval.run_eval --models groq:llama-3.3-70b-versatile ollama:qwen2.5-coder:7b --runs 3
  python -m eval.run_eval --report-only                             # rebuild the report from saved raw results

Every finished review is appended to eval/raw_results.jsonl, so an interrupted run RESUMES where it stopped.
The LLM cache is disabled here, so repeated runs are genuinely independent samples.
"""
import argparse
import asyncio
import json
import time
from pathlib import Path

from app.agent.graph import run_review
from app.agent.llm import DEFAULT_MODELS, model_name, set_model
from app.core.config import settings
from app.rag.store import index_knowledge
from eval import metrics

BENCH = Path("samples/benchmark")
TRUTH = Path("samples/ground_truth.json")
MODE_ORDER = ["static_only", "llm_only", "llm_static", "full"]


def parse_model(spec: str) -> tuple:
    provider, _, model = spec.partition(":")
    return provider, model or DEFAULT_MODELS.get(provider, "")


def key_of(r: dict) -> tuple:
    return (r["model"], r["mode"], r["file"], r["run"])


def load_raw(path: Path) -> list:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


async def run_all(args, truth: dict):
    raw_path = Path(args.raw)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    done = {key_of(r) for r in load_raw(raw_path)}
    files = [f for f in sorted(truth) if (not args.files or any(s in f for s in args.files))][: args.limit]
    settings.llm_cache = False
    settings.use_mcp = args.mcp  # evaluation measures review quality; MCP only adds a subprocess per file
    index_knowledge()

    for spec in args.models:
        provider, model = parse_model(spec)
        set_model(provider, model)  # also overrides provider-specific variables such as GROQ_MODEL
        model_id = f"{provider}:{model}"
        for mode in args.modes:
            runs = 1 if mode == "static_only" else args.runs  # no LLM involved: deterministic
            for run in range(1, runs + 1):
                for name in files:
                    rec_key = (model_id if mode != "static_only" else "tools", mode, name, run)
                    if rec_key in done:
                        continue
                    code = (BENCH / name).read_text(encoding="utf-8")
                    t0 = time.perf_counter()
                    rec = {"model": rec_key[0], "mode": mode, "file": name, "run": run,
                           "language": truth[name]["language"]}
                    try:
                        res = await run_review(code, mode, truth[name]["language"], verify_fix=not args.no_fix)
                        rec.update({
                            "findings": [{k: f.get(k) for k in ("line", "severity", "category", "title", "verdict")}
                                         for f in res["findings"]],
                            "test_stats": res["test_stats"], "test_coverage": res["test_coverage"],
                            "fix": {k: res["fix"].get(k) for k in ("attempted", "verified", "score_before", "score_after")}
                            if res.get("fix") else None,
                            "usage": res["usage"], "seconds": round(sum(res["timings"].values()), 2),
                            "warnings": len(res["warnings"])})
                    except Exception as e:  # noqa: BLE001
                        rec.update({"error": str(e)[:300], "findings": [], "usage": {}, "test_stats": {},
                                    "test_coverage": {}, "seconds": round(time.perf_counter() - t0, 2)})
                    with raw_path.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(rec) + "\n")
                    print(f"[{rec['model']} | {mode} | run {run}] {name}: "
                          f"{'ERROR ' + rec['error'] if rec.get('error') else str(len(rec['findings'])) + ' findings'}")
                    done.add(rec_key)


def pm(mean, std, pct=True) -> str:
    return f"{mean * 100:.0f}% ± {std * 100:.0f}" if pct else f"{mean:.2f} ± {std:.2f}"


def write_report(records: list, truth: dict, tol: int, out_path: Path):
    groups = {}
    for r in records:
        groups.setdefault((r["model"], r["mode"]), []).append(r)
    keys = sorted(groups, key=lambda k: (k[0], MODE_ORDER.index(k[1]) if k[1] in MODE_ORDER else 9))
    summ = {k: metrics.summarise(groups[k], truth, tol) for k in keys}
    n_def = sum(len(v["defects"]) for v in truth.values())
    n_clean = sum(v["clean"] for v in truth.values())

    L = ["# Evaluation results", "",
         f"Benchmark: {len(truth)} files ({n_clean} clean), {n_def} labelled defects. Findings are matched to "
         f"defects by line (±{tol}); duplicates on an already-found defect are ignored; every other finding is a "
         "false positive. Values are mean ± std (percentage points) over repeated runs.", "",
         "## Detection by pipeline variant", "",
         "| Model | Mode | Runs | Precision | Recall | F1 | Confirmed by tests* | Clean files with a false alarm |",
         "|---|---|---|---|---|---|---|---|"]
    for k in keys:
        s = summ[k]
        conf = pm(s["confirmed_rate"], s["confirmed_rate_std"]) if k[1] == "full" else "–"
        L.append(f"| {k[0]} | {k[1]} | {s['runs']} | {pm(s['precision'], s['precision_std'])} | "
                 f"{pm(s['recall'], s['recall_std'])} | {pm(s['f1'], s['f1_std'])} | {conf} | "
                 f"{pm(s['clean_fp_files'], s['clean_fp_files_std'])} |")
    L += ["", "\\* share of correctly detected defects whose generated test failed on the code (execution evidence).", ""]

    cats = sorted({c for k in keys for c in summ[k]["by_category"]})
    L += ["## Recall by defect category (and share confirmed by a test)", "",
          "| Category | Defects | " + " | ".join(f"{k[0]} / {k[1]}" for k in keys) + " |",
          "|---|---|" + "---|" * len(keys)]
    for c in cats:
        n = next((summ[k]["by_category"][c]["defects"] for k in keys if c in summ[k]["by_category"]), 0)
        cells = []
        for k in keys:
            v = summ[k]["by_category"].get(c)
            cells.append("–" if not v else f"{v['recall'] * 100:.0f}%" + (f" ({v['confirmed'] * 100:.0f}% conf.)" if k[1] == "full" else ""))
        L.append(f"| {c} | {n} | " + " | ".join(cells) + " |")

    L += ["", "## Cost and speed (per review)", "", "| Model | Mode | Seconds | LLM calls | Input tokens | Output tokens |",
          "|---|---|---|---|---|---|"]
    for k in keys:
        s = summ[k]
        L.append(f"| {k[0]} | {k[1]} | {s['avg_seconds']:.1f} | {s['avg_llm_calls']:.1f} | "
                 f"{s['avg_input_tokens']:.0f} | {s['avg_output_tokens']:.0f} |")

    full = [(k, summ[k]) for k in keys if "tests" in summ[k]]
    if full:
        L += ["", "## Test generation quality (full mode)", "",
              "| Model | Reviews with tests | Tests run (avg) | Retried | Syntax errors | Timeouts | Discarded tests (avg) | Coverage by category (avg per review) |",
              "|---|---|---|---|---|---|---|---|"]
        for k, s in full:
            t = s["tests"]
            cov = ", ".join(f"{c}: {v:.1f}" for c, v in t["coverage"].items())
            L.append(f"| {k[0]} | {t['reviews_with_tests']} | {t['avg_ran']:.1f} | {t['retry_rate'] * 100:.0f}% | "
                     f"{t['syntax_error_rate'] * 100:.0f}% | {t['timeout_rate'] * 100:.0f}% | {t['avg_discarded']:.1f} | {cov} |")
    fixes = [(k, summ[k]) for k in keys if "fix" in summ[k]]
    if fixes:
        L += ["", "## Fix verification (full mode)", "",
              "| Model | Fixes attempted | Verified (strict) | Avg score before | Avg score after |", "|---|---|---|---|---|"]
        for k, s in fixes:
            f = s["fix"]
            L.append(f"| {k[0]} | {f['attempted']} | {f['verified_rate'] * 100:.0f}% | "
                     f"{f['avg_score_before']:.0f} | {f['avg_score_after']:.0f} |")
        L += ["", "Verified = at least one failing test now passes, none of the originally failing tests still fails, "
              "and no previously passing test broke."]
    errs = sum(s["errors"] for s in summ.values())
    if errs:
        L += ["", f"_{errs} reviews failed with an error and are excluded; see the `error` field in the raw file._"]
    out_path.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", nargs="+", default=[f"{settings.llm_provider}:{model_name()}"],
                    help="provider:model, e.g. groq:llama-3.3-70b-versatile ollama:qwen2.5-coder:7b")
    ap.add_argument("--modes", nargs="+", default=MODE_ORDER, choices=MODE_ORDER)
    ap.add_argument("--runs", type=int, default=3, help="repeats per LLM mode (static_only runs once)")
    ap.add_argument("--limit", type=int, default=None, help="only the first N files (quick trial)")
    ap.add_argument("--files", nargs="+", help="only files whose name contains one of these strings")
    ap.add_argument("--tolerance", type=int, default=2, help="line tolerance when matching findings to defects")
    ap.add_argument("--mcp", action="store_true", help="call the analysis tools through the MCP server (slower)")
    ap.add_argument("--no-fix", action="store_true", help="skip fix verification (saves one LLM call per review)")
    ap.add_argument("--raw", default="eval/raw_results.jsonl")
    ap.add_argument("--out", default="eval/results.md")
    ap.add_argument("--report-only", action="store_true")
    args = ap.parse_args()

    truth = json.loads(TRUTH.read_text(encoding="utf-8"))
    if not args.report_only:
        asyncio.run(run_all(args, truth))
    records = load_raw(Path(args.raw))
    if not records:
        raise SystemExit("No results yet.")
    write_report(records, truth, args.tolerance, Path(args.out))


if __name__ == "__main__":
    main()
