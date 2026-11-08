from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import BUGGY, FIXED, GOOD_TESTS, REVIEW


def test_review_history_regression_report_stats(install_llm):
    install_llm(review=REVIEW, tests=[GOOD_TESTS], fix=FIXED)
    with TestClient(app) as c:
        assert "AI Code Review" in c.get("/").text
        assert c.get("/health").json()["status"] == "ok"

        first = c.post("/review", json={"code": BUGGY, "file_name": "avg.py"}).json()
        assert first["language"] == "python" and first["regression"] is None and first["review_id"] == 1

        install_llm(review={**REVIEW, "findings": []})  # developer fixed the bug; reviewer now finds nothing
        second = c.post("/review", json={"code": FIXED, "file_name": "avg.py", "mode": "llm_only"}).json()
        reg = second["regression"]
        assert len(reg["fixed"]) == 1 and reg["new"] == [] and reg["score_now"] > reg["score_previous"]
        assert len(c.get("/history", params={"file_name": "avg.py"}).json()) == 2

        md = c.post("/report", json={"review": first, "code": BUGGY}).text
        assert "Fix verification" in md and "average" in md

        st = c.get("/stats").json()
        assert st["runs"] == 2 and st["total_tokens"] > 0 and st["fix_verified_rate"] == 1.0

        assert c.post("/review", json={"code": "x" * 30000}).status_code == 413
