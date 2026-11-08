"""Turn a review result into a Markdown report (the web page offers it as a download)."""

_ICON = {"confirmed": "🔴 confirmed", "suspected": "🟡 suspected"}


def _cell(text) -> str:
    return str(text or "").replace("|", "\\|").replace("\n", " ")


def to_markdown(r: dict, code: str = "") -> str:
    out = ["# Code review report", "",
           f"- **Language:** {r.get('language')}  |  **Mode:** {r.get('mode')}",
           f"- **Quality score:** {r.get('quality_score')}/100  (penalties: {r.get('score_breakdown')})"]
    fix = r.get("fix") or {}
    if fix.get("attempted"):
        out.append(f"- **After verified fix:** {fix.get('score_after')}/100"
                   f" ({'verified' if fix.get('verified') else 'NOT fully verified'})")
    out += ["", "## Summary", "", r.get("summary") or "_No summary._", "", "## Findings", ""]
    findings = r.get("findings", [])
    if not findings:
        out.append("No issues reported.")
    for f in findings:
        out += [f"### {f['id']} · {f['severity'].upper()} · {_ICON.get(f.get('verdict'), f.get('verdict') or '')} · "
                f"line {f.get('line')}", f"**{f['title']}** ({f['category']}, source: {f['source']})", ""]
        if f.get("snippet"):
            out += ["```", f["snippet"], "```", ""]
        if f.get("explanation"):
            out += [f["explanation"], ""]
        if f.get("failure_scenario"):
            out += [f"**Failure scenario:** {f['failure_scenario']}", ""]
        if f.get("fix"):
            out += [f"**Suggested fix:** {f['fix']}", ""]

    tests = [t for t in r.get("tests", []) if t["name"] != "sandbox"]
    out += ["## Generated tests", ""]
    if tests:
        out += ["| Test | Finding | Category | Result |", "|---|---|---|---|"]
        out += [f"| {_cell(t['name'])} | {t.get('finding_id') or '-'} | {t['category']} | {t['status']} |" for t in tests]
        out += ["", f"Coverage by category: {r.get('test_coverage')}", f"Generation stats: {r.get('test_stats')}"]
    else:
        out.append("No tests were run.")

    if fix.get("attempted"):
        out += ["", "## Fix verification", "",
                f"- Verified: **{fix.get('verified')}** {('(' + fix['reason'] + ')') if fix.get('reason') else ''}",
                f"- Tests before: {fix.get('before')}  →  after: {fix.get('after')}",
                f"- Fixed tests: {fix.get('fixed_tests')}", f"- Still failing: {fix.get('still_failing')}",
                f"- Regressions: {fix.get('regressions')}",
                f"- Static issues: {fix.get('static_issues_before')} → {fix.get('static_issues_after')}"]
        if fix.get("fixed_code"):
            out += ["", "```", fix["fixed_code"].rstrip(), "```"]

    reg = r.get("regression")
    if reg:
        out += ["", "## Changes since last review", "",
                f"Score {reg['score_previous']} → {reg['score_now']}",
                f"- Fixed: {len(reg['fixed'])}  |  New: {len(reg['new'])}  |  Still present: {len(reg['persisting'])}"]
    if r.get("warnings"):
        out += ["", "## Warnings", ""] + [f"- {w}" for w in r["warnings"]]
    out += ["", f"_Timings (s): {r.get('timings')}  ·  Usage: {r.get('usage')}_", ""]
    return "\n".join(out)
