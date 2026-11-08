"""RAG over a folder of markdown knowledge docs, using ChromaDB.

Falls back to simple keyword overlap if ChromaDB (or its embedding model) is unavailable.
"""
import re
from pathlib import Path

from app.core.config import settings

_COLLECTION = "programming_knowledge"


def load_chunks() -> list:
    """Split every .md file into chunks at '## ' headings."""
    chunks = []
    for path in sorted(Path(settings.knowledge_dir).glob("*.md")):
        text = path.read_text(encoding="utf-8")
        parts = re.split(r"\n(?=## )", text)
        for i, part in enumerate(parts):
            part = part.strip()
            if len(part) > 40:
                chunks.append({"id": f"{path.stem}-{i}", "text": part, "source": path.name})
    return chunks


def _collection():
    import chromadb

    client = chromadb.PersistentClient(path=settings.chroma_dir)
    return client.get_or_create_collection(_COLLECTION)


def index_knowledge(force: bool = False) -> int:
    chunks = load_chunks()
    try:
        coll = _collection()
        if force and coll.count():
            ids = coll.get()["ids"]
            coll.delete(ids=ids)
        if coll.count() == 0 and chunks:
            coll.add(
                ids=[c["id"] for c in chunks],
                documents=[c["text"] for c in chunks],
                metadatas=[{"source": c["source"]} for c in chunks],
            )
        return coll.count()
    except Exception:  # noqa: BLE001
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
    except Exception:  # noqa: BLE001
        return [{"text": c["text"], "source": c["source"]} for c in _keyword_retrieve(query, k)]
