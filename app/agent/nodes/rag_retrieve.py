import asyncio

from app.agent.modes import flags
from app.agent.nodes.common import timed
from app.rag.store import retrieve


@timed("rag_retrieve")
async def rag_retrieve_node(state):
    if not flags(state)["rag"]:
        return {"rag_context": []}
    titles = " ".join(f"{f.get('title', '')} {f.get('explanation', '')}" for f in state.get("static_findings", []))
    query = (titles[:600] + " " + state["code"][:800]).strip()
    chunks = await asyncio.to_thread(retrieve, query)
    return {"rag_context": chunks}
