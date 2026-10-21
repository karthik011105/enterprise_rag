import logfire
from flashrank import Ranker, RerankRequest
from app.agents.state import AgentState
from app.services.retrieval.qdrant_service import search_enterprise_knowledge

# Questions whose best match scores below this are treated as "not in the documents".
# Measured: document questions scored 0.67-0.999, off-topic questions scored ~0.0000.
RELEVANCE_THRESHOLD = 0.1

_ranker = None


def _get_ranker():
    global _ranker
    if _ranker is None:
        _ranker = Ranker(model_name="ms-marco-TinyBERT-L-2-v2")
    return _ranker


def retrieve_node(state: AgentState):
    """
    Performs vector search and semantic reranking for technical queries.
    Returns no documents when nothing relevant is found, so the responder can skip the LLM.
    """
    query = state["current_query"]

    with logfire.span("🔍 Knowledge Retrieval"):
        logfire.info(f"Searching Qdrant for: {query}")
        raw_results = search_enterprise_knowledge(query, limit=15)
        logfire.info(f"Retrieved {len(raw_results)} candidates from Vector DB")

        with logfire.span("⚖️ Semantic Reranking"):
            passages = [{"id": i, "text": d["content"]} for i, d in enumerate(raw_results)]
            ranked = _get_ranker().rerank(RerankRequest(query=query, passages=passages)) if passages else []
            top_score = float(ranked[0]["score"]) if ranked else 0.0
            logfire.info(f"Top relevance score: {top_score:.4f} (threshold {RELEVANCE_THRESHOLD})")

            if top_score < RELEVANCE_THRESHOLD:
                logfire.info("🚫 No relevant documents found — LLM will be skipped.")
                return {
                    "documents": [],
                    "status": "No relevant documentation found.",
                    "plan": state["plan"] + ["Context: none relevant"]
                }

            top_docs = [r["text"] for r in ranked[:5]]
            logfire.info("Reranking complete. Kept top 5 most relevant chunks.")

        formatted_docs = [f"CONTENT: {doc}" for doc in top_docs]

    return {
        "documents": formatted_docs,
        "status": "Found technical context.",
        "plan": state["plan"] + ["Context Retrieved"]
    }