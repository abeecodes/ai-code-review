from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from app import storage
from app.agent.graph import run_review
from app.agent.llm import model_name
from app.agent.modes import detect_language
from app.core.config import settings
from app.rag.store import index_knowledge
from app.report import to_markdown
from app.schemas import ReviewRequest, ReviewResponse

WEB = Path(__file__).resolve().parents[1] / "web" / "index.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    index_knowledge()
    yield


app = FastAPI(title="AI-Powered Code Review & Test Generation", version="2.0.0", lifespan=lifespan)


@app.get("/", include_in_schema=False)
async def home():
    return FileResponse(WEB)


@app.get("/health")
async def health():
    return {"status": "ok", "llm_provider": settings.llm_provider, "model": model_name(),
            "mcp": settings.use_mcp, "sandbox": settings.sandbox_mode, "cache": settings.llm_cache}


@app.post("/review", response_model=ReviewResponse)
async def review(req: ReviewRequest):
    if len(req.code) > settings.max_code_chars:
        raise HTTPException(413, f"Code too long (max {settings.max_code_chars} characters).")
    language = detect_language(req.code) if req.language == "auto" else req.language
    previous = storage.last_review(req.file_name) if req.file_name else None

    result = await run_review(req.code, req.mode, language, req.verify_fix)
    if previous:
        result["regression"] = storage.compare(previous["result"], result, previous["id"], previous["created"])
    if req.file_name:
        result["review_id"] = storage.save_review(req.file_name, result)
    storage.log_run(result, settings.llm_provider, model_name())
    return result


class ReportRequest(BaseModel):
    review: ReviewResponse
    code: Optional[str] = ""


@app.post("/report", response_class=PlainTextResponse)
async def report(req: ReportRequest):
    return to_markdown(req.review.model_dump(), req.code or "")


@app.get("/history")
async def history(file_name: str):
    return storage.history(file_name)


@app.get("/stats")
async def stats():
    return storage.stats()


@app.post("/rag/reindex")
async def reindex():
    return {"chunks_indexed": index_knowledge(force=True)}
