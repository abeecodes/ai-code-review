"""LangGraph workflow

 static_analysis -> rag_retrieve -> llm_review -+-> aggregate                (nothing to test / baseline modes)
                                                '-> test_gen <-+            (retry once on bad or hanging tests)
                                                       |       |
                                                       v       |
                                                   test_run ---'
                                                       |
                                                  fix_verify -> aggregate
"""
from langgraph.graph import END, StateGraph

from app.agent.llm import new_usage
from app.agent.modes import flags
from app.agent.nodes.aggregate import aggregate_node
from app.agent.nodes.fix_verify import fix_verify_node
from app.agent.nodes.llm_review import llm_review_node
from app.agent.nodes.rag_retrieve import rag_retrieve_node
from app.agent.nodes.static_analysis import static_analysis_node
from app.agent.nodes.test_gen import new_stats, test_gen_node
from app.agent.nodes.test_run import test_run_node
from app.agent.state import ReviewState
from app.core.config import settings
from app.scoring import is_testable


def _route_after_review(state) -> str:
    has_issues = any(is_testable(f) for f in state.get("findings", []))
    return "test_gen" if flags(state)["tests"] and has_issues else "aggregate"


def _route_after_gen(state) -> str:
    if state.get("test_issue"):
        return "test_gen" if state.get("test_attempt", 1) < settings.max_test_attempts else "aggregate"
    return "test_run" if state.get("test_code") else "aggregate"


def _route_after_run(state) -> str:
    return "test_gen" if state.get("test_issue") else "fix_verify"


def build_graph():
    g = StateGraph(ReviewState)
    for name, fn in [("static_analysis", static_analysis_node), ("rag_retrieve", rag_retrieve_node),
                     ("llm_review", llm_review_node), ("test_gen", test_gen_node), ("test_run", test_run_node),
                     ("fix_verify", fix_verify_node), ("aggregate", aggregate_node)]:
        g.add_node(name, fn)
    g.set_entry_point("static_analysis")
    g.add_edge("static_analysis", "rag_retrieve")
    g.add_edge("rag_retrieve", "llm_review")
    g.add_conditional_edges("llm_review", _route_after_review, {"test_gen": "test_gen", "aggregate": "aggregate"})
    g.add_conditional_edges("test_gen", _route_after_gen,
                            {"test_gen": "test_gen", "test_run": "test_run", "aggregate": "aggregate"})
    g.add_conditional_edges("test_run", _route_after_run, {"test_gen": "test_gen", "fix_verify": "fix_verify"})
    g.add_edge("fix_verify", "aggregate")
    g.add_edge("aggregate", END)
    return g.compile()


graph = build_graph()


async def run_review(code: str, mode: str = "full", language: str = "python", verify_fix: bool = True) -> dict:
    usage = new_usage()
    final = await graph.ainvoke({
        "code": code, "mode": mode, "language": language, "verify_fix": verify_fix, "warnings": [],
        "timings": {}, "test_stats": new_stats(), "test_attempt": 0, "test_issue": "",
    })
    result = final["result"]
    result["usage"] = dict(usage)
    return result
