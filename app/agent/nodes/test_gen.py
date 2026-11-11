"""Generate tests for the reported findings. Rejected output (syntax error, forbidden calls) is retried
once with feedback; the LangGraph loop in graph.py drives the retry."""
import re

from app.agent.llm import complete_json
from app.agent.nodes.common import as_text, number_lines, timed
from app.sandbox.runner import collect_error, count_tests, is_blocked
from app.scoring import is_testable
from app.tools.syntax import validate_test_structure

CATEGORY_RULES = """- Name every test test_<finding_id>_<category>_<short_description>, where category is one of:
  normal, boundary, empty, invalid_type, large_input, malicious.
  Examples: test_f2_empty_list_returns_zero, test_f1_boundary_single_item.
- For each finding write 3-4 tests, including at least one "empty" or "boundary" edge case
  and one "invalid_type" or "malicious" case where it applies.
- Each finding lists a "failing input". Write at least one test that calls the code with exactly that input.
- Expected values come from the function's intent: its name, its docstring and common sense about correct
  behaviour. Never copy the value the current code returns, because the current code may be the bug."""

PY_SYSTEM = """You write pytest tests that check whether reported defects are real.
Return ONLY a JSON object: {"test_code": "<full contents of test_target.py>"}

Rules:
- The code under test is importable as `target` (use `import target`; do not copy its source).
- Each test asserts the CORRECT behaviour, so it FAILS on the buggy code and passes once fixed.
- The file must start with: import pytest, then import target. Every use of pytest.raises needs pytest imported.
- A test name describes the CORRECT behaviour, never the current buggy behaviour. Do not put words like
  "returns_zero" or "returns_default" in a name when the correct behaviour is to raise an error.
- If the code should raise an exception on invalid input, the test expects that exception with pytest.raises.
  A test that expects the buggy result is wrong and must not be written.
""" + CATEGORY_RULES + """
- For hardcoded secrets, inspect the source text with open(target.__file__).read().
- Tests must be deterministic and fast (each test gets a few seconds). Do NOT use network, subprocess, sockets,
  shutil, sleeps, input(), infinite loops, or write files outside the current directory. Use harmless payloads.
- Avoid backslashes in the code. If one is unavoidable, write it as two backslashes inside the JSON string.
- Only test functions that exist in the code."""

JS_SYSTEM = """You write Node.js tests (node:test) that check whether reported defects are real.
Return ONLY a JSON object: {"test_code": "<full contents of test_target.js>"}

Rules:
- Start the file with exactly:
  const test = require('node:test');
  const assert = require('node:assert');
  const target = require('./target.js');
- The code under test is exported from ./target.js; call it as target.fnName(...). Do not copy its source.
- Each test asserts the CORRECT behaviour, so it FAILS on the buggy code and passes once fixed.
- A test name describes the CORRECT behaviour, never the current buggy behaviour.
- If the code should throw on invalid input, the test expects the throw with assert.throws.
  A test that expects the buggy result is wrong and must not be written.
""" + CATEGORY_RULES + """
- Give every test a time limit: test('test_f1_empty_array_returns_zero', { timeout: 3000 }, () => { ... });
- Use assert.throws for expected errors and assert.strictEqual / assert.deepStrictEqual for values.
- For hardcoded secrets read the source: require('node:fs').readFileSync(require.resolve('./target.js'), 'utf8').
- No network, child_process, eval, process.exit, fetch, or file writes. Deterministic and fast.
- Avoid backslashes in the code. If one is unavoidable, write it as two backslashes inside the JSON string.
- Only test functions that exist in the code."""


def new_stats() -> dict:
    return {"attempts": 0, "syntax_errors": 0, "invalid_structure": 0, "blocked": 0, "timeouts": 0, "retries": 0,
            "discarded_unparseable": 0, "generated": 0}


@timed("test_gen")
async def test_gen_node(state):
    language = state.get("language", "python")
    stats = dict(state.get("test_stats") or new_stats())
    attempt = state.get("test_attempt", 0) + 1
    feedback = state.get("test_issue", "")
    stats["attempts"] = attempt
    if attempt > 1:
        stats["retries"] += 1

    findings = [f for f in state.get("findings", []) if is_testable(f)][:8]
    listing = "\n".join(
        f"- {f['id']} (line {f['line']}, {f['category']}, {f['severity']}): {f['title']} -- {f['explanation']}"
        f" | failing input: {f.get('failure_scenario') or 'unknown'}"
        for f in findings)
    user = f"CODE (module `target`):\n{number_lines(state['code'])}\n\nFINDINGS:\n{listing}"
    if feedback and not feedback.startswith("LLM generation failed"):  # provider errors are not model feedback
        user += (f"\n\nYour previous test file was rejected: {feedback}\n"
                 "Write a corrected, complete test file that avoids this problem.")

    test_code, issue = "", ""
    try:
        data = await complete_json(PY_SYSTEM if language == "python" else JS_SYSTEM, user)
        candidate = as_text(data.get("test_code") or data.get("test") or data.get("tests") or data.get("code")).strip()
        candidate = re.sub(r"^```(?:python|javascript|js)?\s*|\s*```$", "", candidate, flags=re.M).strip()
        if not candidate:
            issue = "the test file was empty"
        elif (bad := is_blocked(candidate, language)):
            issue = f"it uses a forbidden call or module ({bad.strip()[:40]}); do not use it"
            stats["blocked"] += 1
        elif (struct_err := validate_test_structure(candidate, state["code"], language, {f["id"] for f in findings})):
            issue = struct_err
            stats["syntax_errors" if struct_err.startswith("syntax error") else "invalid_structure"] += 1
        elif (load_err := collect_error(state["code"], candidate, language)):
            issue = (f"the test file fails to load with this error: {load_err[-250:]}. "
                     "Fix the import or the error and keep every test.")
        else:
            test_code = candidate
        if issue and candidate:
            stats["discarded_unparseable"] += count_tests(candidate, language)
    except Exception as e:  # noqa: BLE001
        # Record the error as the issue so the graph retries (bounded by max_test_attempts) instead of silently
        # skipping test generation.
        msg = f"LLM generation failed: {str(e)[:200]}"
        return {"test_code": "", "test_issue": msg, "test_attempt": attempt, "test_stats": stats,
                "test_results": [], "warnings": [f"Test generation failed: {msg}"]}

    out = {"test_code": test_code, "test_issue": issue, "test_attempt": attempt, "test_stats": stats,
           "test_results": []}
    if issue and attempt >= 2:
        out["warnings"] = [f"Generated tests were discarded after {attempt} attempts: {issue}"]
    return out
