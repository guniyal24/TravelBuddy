"""Vector retrieval over Pinecone returning plain dicts (easy to fake in tests)."""
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

log = logging.getLogger(__name__)


class Retriever:
    def __init__(self, embedder, index, embed_model: str, redis_client=None,
                 query_timeout: float = 20.0):
        self.embedder = embedder
        self.index = index
        self.embed_model = embed_model
        self.redis = redis_client
        self.query_timeout = query_timeout
        # Vector queries run on worker threads so a stalled network call cannot hang a request.
        self._pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="vector-query")
        self._memo: dict[str, list[float]] = {}  # in-process cache (works without Redis)

    def embed(self, text: str) -> list[float]:
        key = f"embedding:{self.embed_model}:{text}"
        if key in self._memo:
            return self._memo[key]
        if self.redis is not None:
            cached = self.redis.get(key)
            if cached:
                return json.loads(cached)
        vec = self.embedder.embeddings.create(
            model=self.embed_model, input=[text], encoding_format="float"
        ).data[0].embedding
        self._memo[key] = vec
        if self.redis is not None:
            self.redis.setex(key, 86400, json.dumps(vec))
        return vec

    def search(self, query: str, top_k: int = 12, filter: dict | None = None) -> list[dict]:
        """Return [{id, score, name, type, city, text}] best-first; [] on failure."""
        try:
            kwargs = {"filter": filter} if filter else {}
            vec = self.embed(query)
            future = self._pool.submit(
                lambda: self.index.query(vector=vec, top_k=top_k, include_metadata=True, **kwargs))
            res = future.result(timeout=self.query_timeout)
        except FutureTimeout:
            log.error("Vector search timed out after %.0fs; continuing without results",
                      self.query_timeout)
            return []
        except Exception:
            log.exception("Vector search failed")
            return []
        out = []
        for m in res["matches"]:
            md = m.get("metadata") or {}
            out.append({
                "id": m["id"], "score": m.get("score", 0.0), "name": md.get("name", ""),
                "type": md.get("type", ""), "city": md.get("city", ""),
                "text": md.get("semantic_text", ""),
            })
        return out
