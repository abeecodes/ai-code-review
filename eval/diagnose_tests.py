"""Oracle-based test diagnosis: a good generated test fails on the buggy sample and passes on its fix.

Run: python -m eval.diagnose_tests --files division_by_zero_average.py bare_except.py
"""
import argparse
import asyncio
from pathlib import Path

from app.agent.graph import run_review
from app.agent.llm import set_model
from app.core.config import settings
from app.sandbox.runner import run_tests

BENCH, FIXED = Path("samples/benchmark"), Path("samples/fixed")
LOAD_ERRORS = {"sandbox", "test_target"}  # the generated test file did not load


def classify(b: dict, f: dict) -> str:
    if b["name"] in LOAD_ERRORS or f["status"] == "missing":
        return "generation error (file did not load)"
    if "timeout" in (b["status"], f["status"]):
        return "timeout"
    fails_on_bug = b["status"] in ("failed", "error")
    passes_fixed = f["status"] == "passed"
    if fails_on_bug and passes_fixed:
        return "VALID: fails on bug, passes on fix"
    if not fails_on_bug and passes_fixed:
        return "does not reproduce the bug"
    if not fails_on_bug and not passes_fixed:
        return "asserts the bug (wrong expectation)"
    return "fails on both (wrong expectation or broken test)"


async def diagnose(name: str) -> list:
    language = "javascript" if name.endswith(".js") else "python"
    fixed_path = FIXED / name
    if not fixed_path.exists():
        return [(name, "-", "skipped: no corrected version in samples/fixed/")]
    res = await run_review((BENCH / name).read_text(encoding="utf-8"), "full", language, verify_fix=False)
    if not res["test_code"]:
        return [(name, "-", "no tests: " + "; ".join(res["warnings"])[:120])]
    on_fix = {r["name"]: r for r in run_tests(fixed_path.read_text(encoding="utf-8"),
                                              res["test_code"], language, check_blocked=False)}
    return [(name, b["name"], classify(b, on_fix.get(b["name"], {"status": "missing", "name": b["name"]})))
            for b in res["tests"]]


OUTCOMES = [
    "VALID: fails on bug, passes on fix",
    "does not reproduce the bug",
    "asserts the bug (wrong expectation)",
    "fails on both (wrong expectation or broken test)",
    "generation error (file did not load)",
]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="ollama:qwen2.5-coder:7b")
    ap.add_argument("--files", nargs="+", required=True)
    args = ap.parse_args()
    provider, _, model = args.model.partition(":")
    set_model(provider, model)  # also overrides provider-specific variables such as GROQ_MODEL
    settings.llm_cache, settings.use_mcp = False, False

    rows = []
    for name in args.files:
        rows += await diagnose(name)

    detail = ["| File | Test | Result |", "|---|---|---|"]
    detail += [f"| {a} | {b} | {c} |" for a, b, c in rows]

    counts = {o: 0 for o in OUTCOMES}
    skipped = 0
    for _, _, c in rows:
        if c in counts:
            counts[c] += 1
        else:
            skipped += 1  # e.g. "no tests" or "skipped" rows; reported separately

    total = sum(counts.values())
    summary = [f"| Outcome | Count | Share of {total} tests |", "|---|---|---|"]
    summary += [f"| {o} | {n} | {n / total:.0%} |" if total else f"| {o} | {n} | - |"
                for o, n in counts.items()]
    summary += ["", f"Files with no tests or no corrected version: {skipped} row(s)",
                f"Model: {args.model}"]

    text = "\n".join(["## Outcomes", ""] + summary + ["", "## Detail", ""] + detail) + "\n"
    print(text)
    out = Path(f"eval/diagnosis_{provider}_{model.replace('/', '_').replace(':', '_')}.md")
    out.write_text(text, encoding="utf-8")
    print(f"Saved to {out}")


if __name__ == "__main__":
    asyncio.run(main())