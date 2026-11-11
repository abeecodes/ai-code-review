import json

from app.agent.llm import complete_json
from app.agent.modes import flags
from app.agent.nodes.common import number_lines, timed
from app.schemas import Finding, normalize_severity

SYSTEM = """You are a senior code reviewer. Review the {language} code and return ONLY a JSON object:
{
  "summary": "2-3 sentence overall assessment",
  "quality_score": 0-100,
  "findings": [
    {"line": int, "severity": "critical|high|medium|low|info",
     "category": "bug|security|maintainability|performance",
     "title": "short title", "explanation": "why it is a problem",
     "failure_scenario": "one concrete input that triggers it, e.g. average([]) raises ZeroDivisionError",
     "fix": "concrete fix, with a short code snippet if useful",
     "source": "llm|bandit|ruff|eslint"}
  ]
}
Rules: only report real issues; merge duplicates between tool output and your own analysis;
use the reference knowledge when relevant; reference line numbers from the numbered code."""


def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _snippet(code: str, line):
    lines = code.splitlines()
    if isinstance(line, int) and 1 <= line <= len(lines):
        return lines[line - 1].strip()
    return ""


def _from_static(static: list, code: str) -> list:
    out, seen = [], set()
    for s in static:
        key = (s.get("line"), s.get("title"))
        if key in seen:
            continue
        seen.add(key)
        out.append(Finding(
            id=f"f{len(out) + 1}", line=s.get("line"), snippet=_snippet(code, s.get("line")),
            severity=normalize_severity(s.get("severity")), category=s.get("category", "bug"),
            title=s.get("title", "issue"), explanation=s.get("explanation", ""),
            source=s.get("source", "static")).model_dump())
    return out


@timed("llm_review")
async def llm_review_node(state):
    static = state.get("static_findings", [])
    if not flags(state)["llm"]:  # static_only baseline: report the tools' findings as they are
        return {"findings": _from_static(static, state["code"]), "summary": "Static analysis only (no LLM).",
                "quality_score": 0}

    rag = state.get("rag_context", [])
    parts = [f"CODE:\n{number_lines(state['code'])}"]
    if static:
        parts.append("STATIC ANALYSIS OUTPUT:\n" + json.dumps(static, indent=1))
    if rag:
        parts.append("REFERENCE KNOWLEDGE:\n" + "\n---\n".join(f"[{c['source']}] {c['text']}" for c in rag))
    try:
        data = await complete_json(SYSTEM.replace("{language}", state.get("language", "python")),
                                   "\n\n".join(parts))
    except Exception as e:  # noqa: BLE001
        return {"findings": _from_static(static, state["code"]),
                "summary": "LLM review failed; showing static analysis only.",
                "quality_score": 0, "warnings": [f"LLM review failed: {e}"]}

    findings, warnings = [], []
    raw_findings = data.get("findings")
    if not isinstance(raw_findings, list):
        warnings.append(f"The LLM did not return a list of findings (got {type(raw_findings).__name__}); none used.")
        raw_findings = []
    for i, raw in enumerate(raw_findings, 1):
        try:
            line = _to_int(raw.get("line"))
            findings.append(Finding(
                id=f"f{i}", line=line, snippet=_snippet(state["code"], line),
                severity=normalize_severity(raw.get("severity")),
                category=str(raw.get("category", "bug")).lower(), title=raw["title"],
                explanation=raw.get("explanation", ""), failure_scenario=raw.get("failure_scenario", ""),
                fix=raw.get("fix", ""), source="llm",
            ).model_dump())
        except Exception:  # noqa: BLE001
            warnings.append(f"Skipped a malformed finding: {raw}")
    score = _to_int(data.get("quality_score")) or 0
    return {"findings": findings, "summary": str(data.get("summary") or ""),
            "quality_score": max(0, min(100, score)), "warnings": warnings}
