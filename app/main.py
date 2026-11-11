import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from app import storage
from app.agent.graph import run_review
from app.agent.llm import check_llm_connection, close_clients, model_name
from app.agent.modes import detect_language
from app.core.config import settings
from app.rag.store import index_knowledge
from app.report import to_markdown
from app.schemas import ReviewRequest, ReviewResponse

log = logging.getLogger("review")
WEB = Path(__file__).resolve().parents[1] / "web" / "index.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    index_knowledge()
    yield
    await close_clients()


app = FastAPI(title="AI-Powered Code Review & Test Generation", version="2.0.0", lifespan=lifespan)


@app.get("/", include_in_schema=False)
async def home():
    return FileResponse(WEB)


@app.get("/health")
async def health():
    return {"status": "ok", "llm_provider": settings.llm_provider, "model": model_name(),
            "mcp": settings.use_mcp, "sandbox": settings.sandbox_mode,
            "sandbox_isolated": settings.sandbox_mode == "docker", "cache": settings.llm_cache}


@app.get("/health/llm")
async def health_llm():
    return await check_llm_connection()


@app.post("/review", response_model=ReviewResponse)
async def review(req: ReviewRequest):
    if len(req.code) > settings.max_code_chars:
        raise HTTPException(413, f"Code too long (max {settings.max_code_chars} characters).")
    language = detect_language(req.code) if req.language == "auto" else req.language
    try:
        result = await run_review(req.code, req.mode, language, req.verify_fix)
    except Exception as exc:
        log.exception("review failed")
        raise HTTPException(500, f"Review failed: {type(exc).__name__}: {exc}") from exc

    # History is a convenience: a database problem must not throw away a review that already succeeded.
    try:
        previous = storage.last_review(req.file_name) if req.file_name else None
        if previous:
            result["regression"] = storage.compare(previous["result"], result, previous["id"], previous["created"])
        if req.file_name:
            result["review_id"] = storage.save_review(req.file_name, result)
        storage.log_run(result, settings.llm_provider, model_name())
    except Exception as exc:  # noqa: BLE001
        log.exception("could not save review history")
        result.setdefault("warnings", []).append(f"Review history could not be saved: {type(exc).__name__}: {exc}")
    return result


class ReportRequest(BaseModel):
    review: ReviewResponse
    code: Optional[str] = ""


@app.post("/report", response_class=PlainTextResponse)
async def report(req: ReportRequest):
    return to_markdown(req.review.model_dump(), req.code or "")


@app.get("/history")
async def history(file_name: str, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    return storage.history(file_name, limit, offset)


@app.get("/stats")
async def stats():
    return storage.stats()


@app.post("/rag/reindex")
async def reindex():
    return {"chunks_indexed": index_knowledge(force=True)}
