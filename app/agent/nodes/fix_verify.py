"""Ask the LLM for a fixed version of the code, then run the SAME tests on it."""
import asyncio

from app.agent.llm import complete_json
from app.agent.modes import flags
from app.agent.nodes.common import number_lines, timed
from app.fix_logic import evaluate_fix
from app.sandbox.runner import run_tests
from app.schemas import FixReport
from app.scoring import failing_tests_by_finding
from app.tools.analyzers import analyze
from app.tools.syntax import syntax_error

SYSTEM = """You repair code. Return ONLY a JSON object: {"fixed_code": "<the complete corrected source file>"}
Rules:
- Fix ONLY the listed confirmed defects, with the smallest possible change.
- Keep every function/class name, signature and the behaviour for valid input.
- Return the whole file, runnable as-is: no placeholders, no markdown fences inside the string.
- Where invalid input must be rejected, raise ValueError (Python) or throw an Error (JavaScript)."""


def _static_count(code: str, language: str) -> int:
    return sum(1 for f in analyze(code, language) if f.get("severity") != "info")


@timed("fix_verify")
async def fix_verify_node(state):
    if not (flags(state)["tests"] and state.get("verify_fix")):
        return {}
    language, code, results = state.get("language", "python"), state["code"], state.get("test_results", [])
    findings = state.get("findings", [])
    failing = failing_tests_by_finding(results)
    if not failing:
        return {"fix": FixReport(reason="No confirmed defects to fix.").model_dump()}

    confirmed = [f for f in findings if f["id"] in failing]
    listing = "\n".join(f"- {f['id']} (line {f['line']}): {f['title']} -- {f['explanation']}. Suggested fix: {f['fix']}"
                        for f in confirmed)
    user = f"CODE:\n{number_lines(code)}\n\nCONFIRMED DEFECTS:\n{listing}"

    fixed, reason = "", ""
    for _ in range(2):
        prompt = user if not reason else user + f"\n\nYour previous answer was rejected: {reason}. Try again."
        try:
            data = await complete_json(SYSTEM, prompt)
        except Exception as e:  # noqa: BLE001
            return {"fix": FixReport(attempted=True, reason=f"Fix generation failed: {e}").model_dump()}
        candidate = (data.get("fixed_code") or "").strip("\n")
        if not candidate.strip():
            reason = "the fixed code was empty"
        elif candidate.strip() == code.strip():
            reason = "the code was returned unchanged"
        elif (err := syntax_error(candidate, language)):
            reason = f"syntax error: {err}"
        else:
            fixed, reason = candidate + "\n", ""
            break
    if not fixed:
        return {"fix": FixReport(attempted=True, reason=f"No valid fix produced: {reason}").model_dump()}

    after = await asyncio.to_thread(run_tests, fixed, state["test_code"], language)
    if any(r["name"] == "sandbox" for r in after):
        return {"fix": FixReport(attempted=True, fixed_code=fixed,
                                 reason=f"Tests could not run on the fixed code: {after[0]['message']}").model_dump()}

    ev = evaluate_fix(results, after, findings)
    report = FixReport(
        attempted=True, fixed_code=fixed, reason="" if ev["verified"] else "Not all checks passed (see lists).",
        static_issues_before=len([s for s in state.get("static_findings", []) if s.get("severity") != "info"]),
        static_issues_after=await asyncio.to_thread(_static_count, fixed, language) if flags(state)["static"] else 0,
        **ev)
    return {"fix": report.model_dump()}
