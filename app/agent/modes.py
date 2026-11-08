"""Pipeline variants. They exist so the evaluation can measure what each component adds."""
import re

MODES = {
    "full":        {"static": True,  "rag": True,  "llm": True,  "tests": True},
    "llm_static":  {"static": True,  "rag": False, "llm": True,  "tests": False},
    "llm_only":    {"static": False, "rag": False, "llm": True,  "tests": False},
    "static_only": {"static": True,  "rag": False, "llm": False, "tests": False},
}


def flags(state) -> dict:
    return MODES.get(state.get("mode") or "full", MODES["full"])


_JS = re.compile(r"\b(function|const|let|var)\b|=>|console\.|require\(|module\.exports")
_PY = re.compile(r"^\s*(def |class |import |from \w+ import )|:\s*$|\bself\b|\bNone\b|\bTrue\b", re.M)


def detect_language(code: str) -> str:
    return "javascript" if len(_JS.findall(code)) > len(_PY.findall(code)) else "python"
