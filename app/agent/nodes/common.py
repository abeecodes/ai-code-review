import functools
import time


def timed(name: str):
    """Record each node's runtime in state['timings']."""
    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(state):
            start = time.perf_counter()
            out = dict(await fn(state))
            out["timings"] = {**state.get("timings", {}), name: round(time.perf_counter() - start, 2)}
            return out
        return wrapper
    return deco


def number_lines(code: str) -> str:
    return "\n".join(f"{i + 1:>4}| {line}" for i, line in enumerate(code.splitlines()))
