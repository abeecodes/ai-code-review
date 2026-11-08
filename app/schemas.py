from typing import Literal, Optional

from pydantic import BaseModel, Field

Severity = Literal["critical", "high", "medium", "low", "info"]
Mode = Literal["full", "llm_static", "llm_only", "static_only"]

_SEV_MAP = {
    "critical": "critical", "blocking": "critical",
    "high": "high", "error": "high",
    "medium": "medium", "warning": "medium", "moderate": "medium",
    "low": "low", "suggestion": "low",
    "info": "info", "informational": "info",
}


def normalize_severity(value) -> str:
    return _SEV_MAP.get(str(value or "medium").strip().lower(), "medium")


class ReviewRequest(BaseModel):
    code: str = Field(min_length=1)
    mode: Mode = "full"
    language: Literal["auto", "python", "javascript"] = "auto"
    verify_fix: bool = True
    file_name: Optional[str] = None   # set it to enable regression mode (compare with last review)


class Finding(BaseModel):
    id: str
    line: Optional[int] = None
    severity: Severity = "medium"
    category: str = "bug"          # bug | security | maintainability | performance
    title: str
    snippet: str = ""              # exact source line, filled by code, not the LLM
    explanation: str = ""
    failure_scenario: str = ""     # a concrete input that triggers the problem
    fix: str = ""
    source: str = "llm"            # llm | bandit | ruff | eslint
    verdict: Optional[str] = None  # confirmed | suspected


class TestResult(BaseModel):
    __test__ = False  # stop pytest collecting this class
    name: str
    finding_id: Optional[str] = None
    category: str = "normal"       # normal | boundary | empty | invalid_type | large_input | malicious
    status: Literal["passed", "failed", "error", "timeout"]
    message: str = ""


class FixReport(BaseModel):
    attempted: bool = False
    verified: bool = False         # strict: some test fixed, none still failing, none regressed
    reason: str = ""
    fixed_code: str = ""
    before: dict[str, int] = {}
    after: dict[str, int] = {}
    fixed_tests: list[str] = []
    still_failing: list[str] = []
    regressions: list[str] = []
    resolved_findings: list[str] = []
    score_before: int = 0
    score_after: int = 0
    static_issues_before: int = 0
    static_issues_after: int = 0


class RegressionReport(BaseModel):
    previous_review_id: int
    previous_at: str
    score_previous: int
    score_now: int
    new: list[dict] = []
    fixed: list[dict] = []
    persisting: list[dict] = []


class ReviewResponse(BaseModel):
    summary: str
    quality_score: int
    score_breakdown: dict[str, int] = {}
    language: str = "python"
    mode: str = "full"
    findings: list[Finding]
    tests: list[TestResult] = []
    test_code: str = ""
    test_stats: dict[str, int] = {}
    test_coverage: dict[str, int] = {}
    fix: Optional[FixReport] = None
    regression: Optional[RegressionReport] = None
    static_counts: dict[str, int] = {}
    rag_sources: list[str] = []
    timings: dict[str, float] = {}
    usage: dict[str, int] = {}
    warnings: list[str] = []
    review_id: Optional[int] = None
