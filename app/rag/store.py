"""RAG over a folder of markdown knowledge docs, using ChromaDB.

Falls back to simple keyword overlap if ChromaDB (or its embedding model) is unavailable, and logs a warning
when it does so.
"""
import hashlib
import logging
import re
from pathlib import Path

from app.core.config import settings

log = logging.getLogger("review")
_COLLECTION = "programming_knowledge"
_collections = {}  # one persistent client per directory; creating a client per query is slow and leaks handles


def _digest(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def load_chunks() -> list:
    """Split every .md file into chunks at '## ' headings."""
    chunks = []
    for path in sorted(Path(settings.knowledge_dir).glob("*.md")):
        text = path.read_text(encoding="utf-8")
        parts = re.split(r"\n(?=## )", text)
        for i, part in enumerate(parts):
            part = part.strip()
            if len(part) > 40:
                chunks.append({"id": f"{path.stem}-{i}", "text": part, "source": path.name, "hash": _digest(part)})
    return chunks


def _collection():
    key = str(Path(settings.chroma_dir).resolve())
    if key not in _collections:
        import chromadb

        client = chromadb.PersistentClient(path=settings.chroma_dir)
        _collections[key] = client.get_or_create_collection(_COLLECTION)
    return _collections[key]


def reset_cache():
    _collections.clear()


def index_knowledge(force: bool = False) -> int:
    """Bring the vector index in line with the files: add new chunks, update edited ones, delete removed ones.
    Unchanged chunks are not re-embedded."""
    chunks = load_chunks()
    try:
        coll = _collection()
        existing = coll.get(include=["metadatas"])
        old = {i: (m or {}).get("hash") for i, m in zip(existing["ids"], existing["metadatas"], strict=False)}
        wanted = {c["id"] for c in chunks}
        stale = [i for i in old if i not in wanted]
        changed = [c for c in chunks if force or old.get(c["id"]) != c["hash"]]
        if stale:
            coll.delete(ids=stale)
        if changed:
            coll.upsert(ids=[c["id"] for c in changed], documents=[c["text"] for c in changed],
                        metadatas=[{"source": c["source"], "hash": c["hash"]} for c in changed])
        return coll.count()
    except Exception as exc:  # noqa: BLE001
        log.warning("vector index unavailable (%s: %s); retrieval will use keyword matching", type(exc).__name__, exc)
        return len(chunks)


def _keyword_retrieve(query: str, k: int) -> list:
    words = set(re.findall(r"[a-z]{4,}", query.lower()))
    scored = []
    for c in load_chunks():
        overlap = len(words & set(re.findall(r"[a-z]{4,}", c["text"].lower())))
        scored.append((overlap, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for s, c in scored[:k] if s > 0]


def retrieve(query: str, k: int | None = None) -> list:
    """Return the top-k chunks as [{text, source}]."""
    k = k or settings.rag_top_k
    try:
        coll = _collection()
        if coll.count() == 0:
            index_knowledge()
        res = coll.query(query_texts=[query], n_results=k)
        docs = res["documents"][0]
        metas = res["metadatas"][0]
        return [{"text": d, "source": m.get("source", "")} for d, m in zip(docs, metas, strict=False)]
    except Exception as exc:  # noqa: BLE001
        log.warning("semantic retrieval failed (%s: %s); using keyword matching", type(exc).__name__, exc)
        return [{"text": c["text"], "source": c["source"]} for c in _keyword_retrieve(query, k)]
