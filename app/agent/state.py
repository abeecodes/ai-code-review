import operator
from typing import Annotated, TypedDict


class ReviewState(TypedDict, total=False):
    code: str
    mode: str                      # full | llm_static | llm_only | static_only
    language: str                  # python | javascript
    verify_fix: bool
    static_findings: list
    rag_context: list              # [{text, source}]
    findings: list
    summary: str
    quality_score: int
    test_code: str
    test_attempt: int
    test_issue: str                # why the last attempt was rejected (drives the retry loop)
    test_stats: dict
    test_results: list
    fix: dict
    timings: dict
    warnings: Annotated[list, operator.add]
    result: dict
