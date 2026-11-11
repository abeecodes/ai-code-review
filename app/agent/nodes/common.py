import functools
import logging
import time

log = logging.getLogger("review")


def timed(name: str, fail_soft: bool = True):
    """Record each node's runtime in state['timings'].

    With fail_soft (the default) an unexpected exception inside a node becomes a warning instead of aborting the
    whole review, so a crash in one step (say, the fix generator) cannot throw away the findings and tests that
    were already produced. The aggregate node opts out: without it there is no result to return."""
    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(state):
            start = time.perf_counter()
            try:
                out = dict(await fn(state))
            except Exception as exc:  # noqa: BLE001
                if not fail_soft:
                    raise
                log.exception("node %s failed", name)
                out = {"warnings": [f"{name} failed: {type(exc).__name__}: {exc}"]}
            out["timings"] = {**state.get("timings", {}), name: round(time.perf_counter() - start, 2)}
            return out
        return wrapper
    return deco


def number_lines(code: str) -> str:
    return "\n".join(f"{i + 1:>4}| {line}" for i, line in enumerate(code.splitlines()))


def as_text(value) -> str:
    """LLM fields are supposed to be strings; accept a list of lines, ignore anything else."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(str(v) for v in value)
    return ""
