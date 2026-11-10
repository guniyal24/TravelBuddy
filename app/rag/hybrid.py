"""Hybrid RAG (Pinecone vectors + Neo4j graph + FlashRank re-ranking).

Phase 0 port of VietBot's engine. Phase 1 replaces this linear pipeline with a
Self-RAG LangGraph (retrieve -> grade -> rewrite -> generate -> groundedness check).
"""
import json
import logging
from collections.abc import Generator
from typing import Any

import httpx
from flashrank import Ranker, RerankRequest
from openai import OpenAI
from pinecone import Pinecone

from app.config import Settings
from app.db.graph import GraphStore

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are an Uttarakhand travel assistant. Answer using only the provided context. "
    "If the context does not contain the answer, say so. Do not reveal your reasoning steps."
)


class HybridRAG:
    def __init__(self, settings: Settings, store: GraphStore, redis_client=None):
        self.s = settings
        self.store = store
        self.redis = redis_client
        http = httpx.Client(trust_env=False)
        self.llm = OpenAI(
            api_key=settings.llm_api_key, base_url=settings.llm_base_url, http_client=http
        )
        self.embedder = OpenAI(
            api_key=settings.llm_api_key, base_url=settings.embed_base_url, http_client=http
        )
        try:
            self.ranker = Ranker(model_name="ms-marco-TinyBERT-L-2-v2", cache_dir="./opt")
        except Exception:  # model download / init can fail offline; degrade to vector order
            log.warning("FlashRank unavailable; using raw vector ranking.")
            self.ranker = None
        pc = Pinecone(api_key=settings.pinecone_api_key)
        self._ensure_index(pc)
        self.index = pc.Index(settings.pinecone_index_name)

    def _ensure_index(self, pc: Pinecone) -> None:
        if self.s.pinecone_index_name not in pc.list_indexes().names():
            pc.create_index(
                name=self.s.pinecone_index_name,
                dimension=self.s.pinecone_vector_dim,
                metric="cosine",
                spec={"serverless": {"cloud": "aws", "region": "us-east-1"}},
            )

    # --- embeddings (cached) ---
    def embed_text(self, text: str) -> list[float]:
        key = f"embedding:{text}"
        if self.redis is not None:
            cached = self.redis.get(key)
            if cached:
                return json.loads(cached)
        resp = self.embedder.embeddings.create(model=self.s.embed_model, input=[text])
        emb = resp.data[0].embedding
        if self.redis is not None:
            self.redis.setex(key, 86400, json.dumps(emb))
        return emb

    # --- routing ---
    def classify_intent(self, query: str) -> str:
        try:
            resp = self.llm.chat.completions.create(
                model=self.s.router_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Classify: 'general_chat' or 'travel_search'. Output label only."
                        ),
                    },
                    {"role": "user", "content": query},
                ],
                temperature=0.0,
                max_tokens=10,
            )
            return resp.choices[0].message.content.strip().lower()
        except Exception:
            log.exception("Intent classification failed; defaulting to travel_search")
            return "travel_search"

    # --- retrieval ---
    def vector_search(self, query: str, top_k: int = 20) -> list[dict[str, Any]]:
        try:
            vec = self.embed_text(query)
            return self.index.query(vector=vec, top_k=top_k, include_metadata=True)["matches"]
        except Exception:
            log.exception("Pinecone query failed")
            return []

    def rerank(self, query: str, candidates: list[dict[str, Any]], keep: int = 5) -> list[dict]:
        passages = [
            {
                "id": c["id"],
                "text": (c.get("metadata") or {}).get("semantic_text", "")[:500],
                "meta": c.get("metadata") or {},
            }
            for c in candidates
        ]
        if not passages:
            return []
        if self.ranker is None:
            return passages[:keep]
        return self.ranker.rerank(RerankRequest(query=query, passages=passages))[:keep]

    # --- generation ---
    @staticmethod
    def _build_context(matches: list[dict], graph: list[dict]) -> str:
        lines = ["### Matches:"]
        for m in matches:
            meta = m.get("meta") or m.get("metadata") or {}
            lines.append(f"- {meta.get('name')} ({meta.get('type')}): {meta.get('city', '')}")
        lines.append("\n### Connections:")
        lines += [
            f"- {f['source_id']} --[{f['rel']}]--> {f['name']} ({f['desc']})" for f in graph
        ]
        return "\n".join(lines)

    @staticmethod
    def _clean_history(history: list[dict] | None) -> list[dict]:
        out = []
        for msg in history or []:
            role = "assistant" if msg.get("role") == "bot" else msg.get("role", "user")
            out.append({"role": role, "content": msg.get("content", "")})
        return out

    def _stream(self, model: str, messages: list[dict]) -> Generator[str, None, None]:
        stream = self.llm.chat.completions.create(model=model, messages=messages, stream=True)
        for chunk in stream:
            if chunk.choices:
                yield chunk.choices[0].delta.content or ""

    def _general_chat(self, query: str) -> Generator[str, None, None]:
        yield from self._stream(
            self.s.chat_model,
            [
                {"role": "system", "content": "You are a polite Uttarakhand travel assistant."},
                {"role": "user", "content": query},
            ],
        )

    def retrieve(self, query: str) -> list[dict]:
        """Broad vector search (20) narrowed by the re-ranker to the top 5."""
        return self.rerank(query, self.vector_search(query, top_k=20), keep=5)

    def _travel_search(
        self, query: str, session_id: str, history: list
    ) -> Generator[str, None, None]:
        matches = self.retrieve(query)
        match_ids = [m["id"] for m in matches]
        graph = self.store.fetch_graph_context(match_ids)
        context = self._build_context(matches, graph)

        messages = (
            [{"role": "system", "content": SYSTEM_PROMPT}]
            + self._clean_history(history)
            + [{"role": "user", "content": f"Context:\n{context}\n\nQuestion: {query}"}]
        )
        full = []
        for token in self._stream(self.s.reasoning_model, messages):
            full.append(token)
            yield token
        self.store.log_interaction(session_id, query, "".join(full), match_ids)

    def get_answer(
        self, query: str, session_id: str, history: list | None = None
    ) -> Generator[str, None, None]:
        if "general" in self.classify_intent(query):
            yield from self._general_chat(query)
        else:
            yield from self._travel_search(query, session_id, history or [])
