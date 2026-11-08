"""Generate tests for the reported findings. Rejected output (syntax error, forbidden calls) is retried
once with feedback; the LangGraph loop in graph.py drives the retry."""
from app.agent.llm import complete_json
from app.agent.nodes.common import number_lines, timed
from app.sandbox.runner import count_tests, is_blocked
from app.tools.syntax import syntax_error

CATEGORY_RULES = """- Name every test test_<finding_id>_<category>_<short_description>, where category is one of:
  normal, boundary, empty, invalid_type, large_input, malicious.
  Examples: test_f2_empty_list_returns_zero, test_f1_boundary_single_item.
- For each finding write 3-4 tests, including at least one "empty" or "boundary" edge case
  and one "invalid_type" or "malicious" case where it applies."""

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
    return {"attempts": 0, "syntax_errors": 0, "blocked": 0, "timeouts": 0, "retries": 0,
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

    findings = [f for f in state.get("findings", []) if f["severity"] != "info"][:8]
    listing = "\n".join(
        f"- {f['id']} (line {f['line']}, {f['category']}, {f['severity']}): {f['title']} -- {f['explanation']}"
        for f in findings)
    user = f"CODE (module `target`):\n{number_lines(state['code'])}\n\nFINDINGS:\n{listing}"
    if feedback:
        user += (f"\n\nYour previous test file was rejected: {feedback}\n"
                 "Write a corrected, complete test file that avoids this problem.")

    test_code, issue = "", ""
    try:
        data = await complete_json(PY_SYSTEM if language == "python" else JS_SYSTEM, user)
        candidate = (data.get("test_code") or "").strip()
        if not candidate:
            issue = "the test file was empty"
        elif (err := syntax_error(candidate, language)):
            issue = f"syntax error: {err}"
            stats["syntax_errors"] += 1
        elif language == "python" and "pytest." in candidate and "import pytest" not in candidate:
            issue = "it uses pytest but does not import it; start the file with 'import pytest'"
            stats["syntax_errors"] += 1
        elif (bad := is_blocked(candidate, language)):
            issue = f"it uses a forbidden call or module ({bad.strip()[:40]}); do not use it"
            stats["blocked"] += 1
        else:
            test_code = candidate
        if issue and candidate:
            stats["discarded_unparseable"] += count_tests(candidate, language)
    except Exception as e:  # noqa: BLE001
        return {"test_code": "", "test_issue": "", "test_attempt": attempt, "test_stats": stats,
                "test_results": [], "warnings": [f"Test generation failed: {e}"]}

    out = {"test_code": test_code, "test_issue": issue, "test_attempt": attempt, "test_stats": stats,
           "test_results": []}
    if issue and attempt >= 2:
        out["warnings"] = [f"Generated tests were discarded after {attempt} attempts: {issue}"]
    return out
