"""Self-RAG as a LangGraph state machine.

    retrieve -> grade -> (relevant?) --yes--> expand -> generate -> check --grounded--> END
                   |                                        ^           |
                   +--no--> rewrite -> retrieve (max N)     +-- retry --+ (max M)
                   +--still nothing--> abstain -> END

Why: a plain RAG pipeline answers from whatever the vector store returns, even when it is
irrelevant. Here an LLM grader drops irrelevant documents, the query is rewritten when
nothing relevant is found, the answer is verified against the context before it is shown,
and the bot says "I don't have that" instead of inventing hotels or prices.
"""
import logging
import re
from collections.abc import Generator
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.rag.llm import LLM

log = logging.getLogger(__name__)

MAX_RETRIEVALS = 2
MAX_GENERATIONS = 2
TOP_K = 12
MAX_CONTEXT_DOCS = 6

ABSTAIN_MESSAGE_HI = (
    "मुझे इसकी भरोसेमंद जानकारी अपने उत्तराखंड डेटा में नहीं मिली, इसलिए मैं अंदाज़ा नहीं लगाऊँगा। "
    "मेरा डेटा गढ़वाल और कुमाऊँ के 26 शहरों (जैसे हरिद्वार, ऋषिकेश, मसूरी, नैनीताल, केदारनाथ और "
    "कौसानी) की घूमने की जगहों, ठहरने, खाने और गतिविधियों को कवर करता है।"
)
ABSTAIN_MESSAGE = (
    "I couldn't find reliable information about that in my Uttarakhand data. "
    "My data covers 26 towns across Garhwal and Kumaon (Haridwar, Rishikesh, Mussoorie, "
    "Nainital, Kedarnath, Kausani and more: places to see, stays, food and activities), so I'd "
    "rather not guess."
)

GRADER_SYSTEM = (
    "You grade search results for a travel question about Uttarakhand. You get a question "
    "and numbered candidate documents. Return JSON only: "
    '{"relevant_ids": ["id1", ...]} listing ONLY the documents that directly help answer '
    "the question. Be strict: a hotel is not relevant to a question about food or yoga, and "
    "a place in another town is not relevant to a question about this town. "
    "Return an empty list if none are relevant."
)

REWRITE_SYSTEM = (
    "Rewrite the user's travel question as a short search query for a database of "
    "Uttarakhand places (attractions, stays, eateries, activities, dishes). Use concrete "
    "keywords such as the place type and town. Return only the query text."
)

GENERATE_SYSTEM = (
    "You are an Uttarakhand trip-planning assistant. Use ONLY the facts in CONTEXT. "
    "Cite the source of each recommendation as [id] using the ids in CONTEXT. "
    "If CONTEXT does not contain what is needed, say you don't have that information. "
    "Never invent hotels, restaurants, prices, opening hours or distances. "
    "Only mention place names that appear in CONTEXT; do not add well-known places from "
    "memory. "
    "Distances in CONTEXT are straight-line, not road distances. Be concise. "
    "Reply in the same language and script as the user's question (English, Hindi, or "
    "Hinglish); keep place names and [ids] exactly as in CONTEXT."
)

CHECK_SYSTEM = (
    "You verify an answer against CONTEXT. Return JSON only: "
    '{"grounded": true|false, "unsupported_claims": ["..."]}. '
    "grounded is true only if every factual claim (place names, prices, distances, hours) "
    "is supported by CONTEXT. Every place, hotel, restaurant, ashram or attraction named in the "
    "ANSWER must appear in CONTEXT; if any does not, grounded is false and you list it. "
    "General politeness or advice to check official sources is fine. The ANSWER may be in "
    "Hindi or Hinglish; judge its claims by meaning."
)


class RAGState(TypedDict, total=False):
    question: str
    history: list[dict]
    query: str  # current search query (rewritten on retry)
    retrievals: int
    docs: list[dict]
    relevant: list[dict]
    context: str
    answer: str
    generations: int
    grounded: bool | None
    feedback: str
    abstained: bool
    trace: list[str]


def _clean_id(raw: str) -> str:
    """LLMs echo ids in varied shapes ('id=abc', '[abc]', ' abc '); normalise to 'abc'."""
    return raw.strip().strip("[]()\"'").removeprefix("id=").removeprefix("id:").strip()


def format_entity(doc: dict, ent: dict | None) -> str:
    """One context block per document, enriched with Neo4j properties when available."""
    ent = ent or {}
    head = f"[{doc['id']}] {doc.get('name') or ent.get('name', '')} " \
           f"({doc.get('type', '')}, {doc.get('city', '')})"
    bits = []
    if ent.get("tier"):
        bits.append(f"tier: {ent['tier']}")
    for key, label in (("price_text", "price"), ("hours", "hours"), ("address", "address")):
        if ent.get(key):
            bits.append(f"{label}: {ent[key]}")
    if ent.get("elevation_m") is not None:
        bits.append(f"elevation: {round(ent['elevation_m'])} m")
    text = ent.get("description") or doc.get("text", "")
    return head + (" | " + "; ".join(bits) if bits else "") + f"\n  {text[:400]}"


class SelfRAG:
    def __init__(self, retriever, store, llm: LLM, router_model: str, reasoning_model: str):
        self.retriever = retriever
        self.store = store
        self.llm = llm
        self.grade_model = router_model
        self.gen_model = reasoning_model
        self.graph = self._build()

    # ---- nodes ----
    def _retrieve(self, state: RAGState) -> RAGState:
        query = state.get("query") or state["question"]
        docs = self.retriever.search(query, top_k=TOP_K)
        n = state.get("retrievals", 0) + 1
        trace = [*state.get("trace", []), f"retrieve#{n}: {len(docs)} candidates for {query!r}"]
        return {"query": query, "docs": docs, "retrievals": n, "trace": trace}

    def _grade(self, state: RAGState) -> RAGState:
        docs = state["docs"]
        if not docs:
            return {"relevant": [], "trace": [*state["trace"], "grade: no candidates"]}
        listing = "\n".join(
            f"- id={d['id']} | {d['name']} ({d['type']}, {d['city']}): {d['text'][:200]}"
            for d in docs
        )
        result = self.llm.json(
            self.grade_model,
            [{"role": "system", "content": GRADER_SYSTEM},
             {"role": "user",
              "content": f"Question: {state['question']}\n\nDocuments:\n{listing}"}],
            default={"relevant_ids": []},
        )
        keep = {_clean_id(i) for i in (result.get("relevant_ids") or []) if isinstance(i, str)}
        relevant = [d for d in docs if d["id"] in keep]
        return {
            "relevant": relevant,
            "trace": [*state["trace"], f"grade: kept {len(relevant)}/{len(docs)}"],
        }

    def _route_after_grade(self, state: RAGState) -> str:
        if state["relevant"]:
            return "expand"
        if state.get("retrievals", 0) < MAX_RETRIEVALS:
            return "rewrite"
        return "abstain"

    def _rewrite(self, state: RAGState) -> RAGState:
        new_query = self.llm.complete(
            self.grade_model,
            [{"role": "system", "content": REWRITE_SYSTEM},
             {"role": "user", "content": state["question"]}],
            max_tokens=40,
        ).strip().strip('"')
        return {"query": new_query or state["question"],
                "trace": [*state["trace"], f"rewrite: {new_query!r}"]}

    def _expand(self, state: RAGState) -> RAGState:
        top = state["relevant"][:MAX_CONTEXT_DOCS]
        ids = [d["id"] for d in top]
        entities = self.store.fetch_entities(ids)
        blocks = [format_entity(d, entities.get(d["id"])) for d in top]
        names = {d["id"]: d["name"] for d in top}
        facts = []
        for f in self.store.fetch_graph_context(ids):
            if f.get("rel") == "NEAR" and f.get("km") is not None and f["target_id"] not in names:
                facts.append(f"- {names.get(f['source_id'], f['source_id'])} is {f['km']} km "
                             f"(straight line) from {f['name']} [{f['target_id']}]")
        context = "\n".join(blocks)
        if facts:
            context += "\n\nNearby:\n" + "\n".join(facts[:10])
        return {"context": context, "trace": [*state["trace"], f"expand: {len(top)} docs"]}

    def _generate(self, state: RAGState) -> RAGState:
        messages = [{"role": "system", "content": GENERATE_SYSTEM}]
        for m in state.get("history") or []:
            role = "assistant" if m.get("role") == "bot" else m.get("role", "user")
            messages.append({"role": role, "content": m.get("content", "")})
        user = f"CONTEXT:\n{state['context']}\n\nQUESTION: {state['question']}"
        if state.get("feedback"):
            user += ("\n\nYour previous answer had unsupported claims: "
                     f"{state['feedback']}. Rewrite it using only CONTEXT.")
        messages.append({"role": "user", "content": user})
        answer = self.llm.complete(self.gen_model, messages, temperature=0.2)
        n = state.get("generations", 0) + 1
        return {"answer": answer, "generations": n,
                "trace": [*state["trace"], f"generate#{n}"]}

    def _check(self, state: RAGState) -> RAGState:
        result = self.llm.json(
            self.gen_model,
            [{"role": "system", "content": CHECK_SYSTEM},
             {"role": "user",
              "content": f"CONTEXT:\n{state['context']}\n\nANSWER:\n{state['answer']}"}],
            default={"grounded": True},
        )
        grounded = bool(result.get("grounded", True))
        claims = "; ".join(result.get("unsupported_claims") or [])
        update: RAGState = {"grounded": grounded, "feedback": "" if grounded else claims,
                            "trace": [*state["trace"], f"check: grounded={grounded}"]}
        if not grounded and state["generations"] >= MAX_GENERATIONS:
            update["answer"] = (state["answer"] + "\n\n(Note: some details may not be fully "
                                "verified against my data. Please double-check before booking.)")
        return update

    def _route_after_check(self, state: RAGState) -> str:
        if state["grounded"] or state["generations"] >= MAX_GENERATIONS:
            return "done"
        return "retry"

    def _abstain(self, state: RAGState) -> RAGState:
        hindi = bool(re.search(r"[\u0900-\u097F]", state.get("question", "")))
        return {"answer": ABSTAIN_MESSAGE_HI if hindi else ABSTAIN_MESSAGE,
                "abstained": True, "relevant": [], "grounded": True,
                "trace": [*state["trace"], "abstain: nothing relevant found"]}

    # ---- graph ----
    def _build(self):
        g = StateGraph(RAGState)
        g.add_node("retrieve", self._retrieve)
        g.add_node("grade", self._grade)
        g.add_node("rewrite", self._rewrite)
        g.add_node("expand", self._expand)
        g.add_node("generate", self._generate)
        g.add_node("check", self._check)
        g.add_node("abstain", self._abstain)
        g.add_edge(START, "retrieve")
        g.add_edge("retrieve", "grade")
        g.add_conditional_edges("grade", self._route_after_grade,
                                {"expand": "expand", "rewrite": "rewrite", "abstain": "abstain"})
        g.add_edge("rewrite", "retrieve")
        g.add_edge("expand", "generate")
        g.add_edge("generate", "check")
        g.add_conditional_edges("check", self._route_after_check,
                                {"done": END, "retry": "generate"})
        g.add_edge("abstain", END)
        return g.compile()

    # ---- public API ----
    def run(self, question: str, history: list[dict] | None = None) -> RAGState:
        return self.graph.invoke({"question": question, "history": history or [],
                                  "retrievals": 0, "generations": 0, "trace": []})

    def stream_steps(self, question: str, history: list[dict] | None = None
                     ) -> Generator[tuple[str, dict[str, Any]], None, None]:
        """Yield (node_name, state_update) as each node finishes, for live UI progress."""
        init = {"question": question, "history": history or [], "retrievals": 0,
                "generations": 0, "trace": []}
        for update in self.graph.stream(init, stream_mode="updates"):
            yield from update.items()

    STATUS_LABELS = {
        "retrieve": "Searching places...", "grade": "Checking relevance...",
        "rewrite": "Rephrasing the search...", "expand": "Gathering details...",
        "generate": "Writing the answer...", "check": "Verifying facts...",
        "abstain": "Nothing reliable found...",
    }

    def get_answer(self, query: str, session_id: str, history: list | None = None
                   ) -> Generator[str, None, None]:
        """Same interface as HybridRAG.get_answer so the API can swap implementations.

        Progress is streamed as status chunks wrapped in \x01...\x02 (control characters that
        never occur in answers); the client shows them as live status and drops them from the
        final text. The answer itself follows as plain text.
        """
        state: dict = {}
        for node, update in self.stream_steps(query, history):
            state.update(update)
            label = self.STATUS_LABELS.get(node)
            if label:
                yield f"\x01{label}\x02"
        ids = [d["id"] for d in state.get("relevant", [])]
        yield state["answer"]
        if hasattr(self.store, "log_interaction"):
            self.store.log_interaction(session_id, query, state["answer"], ids)
