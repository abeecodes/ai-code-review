"""SQLite storage: review history (regression mode) and run logs (time, tokens, verdict counts)."""
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT, file_name TEXT, created TEXT, language TEXT,
    mode TEXT, score INTEGER, result_json TEXT);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, created TEXT, mode TEXT, language TEXT,
    provider TEXT, model TEXT, seconds REAL, llm_calls INTEGER, cache_hits INTEGER,
    input_tokens INTEGER, output_tokens INTEGER, findings INTEGER, confirmed INTEGER,
    suspected INTEGER, fix_attempted INTEGER, fix_verified INTEGER);
"""


def _conn():
    folder = Path(settings.data_dir)
    folder.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(folder / "reviews.db")
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    return con


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def save_review(file_name: str, result: dict) -> int:
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO reviews (file_name, created, language, mode, score, result_json) VALUES (?,?,?,?,?,?)",
            (file_name, _now(), result.get("language"), result.get("mode"),
             result.get("quality_score"), json.dumps(result)),
        )
        return cur.lastrowid


def last_review(file_name: str):
    with _conn() as con:
        row = con.execute("SELECT * FROM reviews WHERE file_name = ? ORDER BY id DESC LIMIT 1", (file_name,)).fetchone()
    if not row:
        return None
    return {"id": row["id"], "created": row["created"], "result": json.loads(row["result_json"])}


def history(file_name: str, limit: int = 20) -> list:
    with _conn() as con:
        rows = con.execute(
            "SELECT id, created, language, mode, score FROM reviews WHERE file_name = ? ORDER BY id DESC LIMIT ?",
            (file_name, limit)).fetchall()
    return [dict(r) for r in rows]


def log_run(result: dict, provider: str, model: str):
    u, fix = result.get("usage", {}), result.get("fix") or {}
    verdicts = [f.get("verdict") for f in result.get("findings", [])]
    with _conn() as con:
        con.execute(
            "INSERT INTO runs (created, mode, language, provider, model, seconds, llm_calls, cache_hits,"
            " input_tokens, output_tokens, findings, confirmed, suspected, fix_attempted, fix_verified)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (_now(), result.get("mode"), result.get("language"), provider, model,
             round(sum(result.get("timings", {}).values()), 2), u.get("llm_calls", 0), u.get("cache_hits", 0),
             u.get("input_tokens", 0), u.get("output_tokens", 0), len(verdicts),
             verdicts.count("confirmed"), verdicts.count("suspected"),
             int(bool(fix.get("attempted"))), int(bool(fix.get("verified")))),
        )


def stats() -> dict:
    with _conn() as con:
        rows = [dict(r) for r in con.execute("SELECT * FROM runs").fetchall()]
    if not rows:
        return {"runs": 0}
    n = len(rows)

    def avg(k):
        return round(sum(r[k] for r in rows) / n, 2)

    calls, hits = sum(r["llm_calls"] for r in rows), sum(r["cache_hits"] for r in rows)
    attempted = sum(r["fix_attempted"] for r in rows)
    by_mode = {}
    for r in rows:
        by_mode.setdefault(r["mode"], []).append(r["seconds"])
    return {
        "runs": n, "avg_seconds": avg("seconds"), "avg_llm_calls": avg("llm_calls"),
        "avg_input_tokens": avg("input_tokens"), "avg_output_tokens": avg("output_tokens"),
        "total_tokens": sum(r["input_tokens"] + r["output_tokens"] for r in rows),
        "cache_hit_rate": round(hits / (hits + calls), 2) if hits + calls else 0.0,
        "confirmed_findings": sum(r["confirmed"] for r in rows),
        "suspected_findings": sum(r["suspected"] for r in rows),
        "fix_verified_rate": round(sum(r["fix_verified"] for r in rows) / attempted, 2) if attempted else None,
        "avg_seconds_by_mode": {m: round(sum(v) / len(v), 2) for m, v in by_mode.items()},
    }


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _fingerprint(f: dict) -> str:
    # The source line is stable between reviews of the same file; LLM titles are not.
    return _norm(f.get("snippet")) or _norm(f.get("title"))


def _brief(f: dict) -> dict:
    return {k: f.get(k) for k in ("id", "title", "line", "severity", "snippet")}


def compare(previous: dict, current: dict, previous_id: int, previous_at: str) -> dict:
    """Regression mode: which findings are new, fixed or still present since the last review."""
    prev = {_fingerprint(f): f for f in previous.get("findings", []) if f.get("severity") != "info"}
    cur = {_fingerprint(f): f for f in current.get("findings", []) if f.get("severity") != "info"}
    return {
        "previous_review_id": previous_id, "previous_at": previous_at,
        "score_previous": previous.get("quality_score", 0), "score_now": current.get("quality_score", 0),
        "new": [_brief(f) for k, f in cur.items() if k not in prev],
        "fixed": [_brief(f) for k, f in prev.items() if k not in cur],
        "persisting": [_brief(f) for k, f in cur.items() if k in prev],
    }
