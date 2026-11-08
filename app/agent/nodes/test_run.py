import asyncio

from app.agent.nodes.common import timed
from app.core.config import settings
from app.sandbox.runner import run_tests


@timed("test_run")
async def test_run_node(state):
    results = await asyncio.to_thread(run_tests, state["code"], state["test_code"], state.get("language", "python"))
    stats = dict(state.get("test_stats") or {})
    timeouts = sum(r["status"] == "timeout" for r in results)
    stats["timeouts"] = stats.get("timeouts", 0) + timeouts
    stats["generated"] = stats.get("generated", 0) + sum(r["name"] != "sandbox" for r in results)

    # A hang (per-test or whole run) is retried once with a request for smaller, faster tests.
    if timeouts and state.get("test_attempt", 1) < settings.max_test_attempts:
        return {"test_results": [], "test_issue": "some tests timed out; write smaller, faster tests without loops "
                "or heavy inputs", "test_stats": stats}
    return {"test_results": results, "test_issue": "", "test_stats": stats}
