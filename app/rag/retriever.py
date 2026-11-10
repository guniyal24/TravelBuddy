"""Vector retrieval over Pinecone returning plain dicts (easy to fake in tests)."""
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

log = logging.getLogger(__name__)


class RetrievalError(Exception):
    """Vector search failed (timeout or error), as opposed to finding nothing."""


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

    def search(self, query: str, top_k: int = 12, filter: dict | None = None,
               strict: bool = False, attempts: int = 1) -> list[dict]:
        """Return [{id, score, name, type, city, text}] best-first.

        By default a failure returns [] (chat then declines honestly). With strict=True the
        query is tried `attempts` times and a persistent failure raises RetrievalError, so a
        caller that cannot work without results (the trip planner) can tell "nothing found"
        from "search is down"."""
        last: Exception | None = None
        for attempt in range(max(1, attempts)):
            try:
                kwargs = {"filter": filter} if filter else {}
                vec = self.embed(query)
                future = self._pool.submit(self.index.query, vector=vec, top_k=top_k,
                                           include_metadata=True, **kwargs)
                res = future.result(timeout=self.query_timeout)
                break
            except FutureTimeout as exc:
                last = exc
                log.error("Vector search timed out after %.0fs (attempt %d)",
                          self.query_timeout, attempt + 1)
            except Exception as exc:
                last = exc
                log.exception("Vector search failed (attempt %d)", attempt + 1)
        else:
            if strict:
                raise RetrievalError("The knowledge base did not respond.") from last
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
