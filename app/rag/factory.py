"""Build real RAG components from Settings (shared by the API and the eval harness)."""
import logging
import os

import httpx
from openai import OpenAI
from pinecone import Pinecone

from app.config import Settings
from app.db.graph import GraphStore
from app.rag.llm import LLM
from app.rag.retriever import Retriever
from app.rag.self_rag import SelfRAG

log = logging.getLogger(__name__)


def _client_class():
    """Langfuse's drop-in OpenAI client when LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are
    set (every LLM call is then traced to Langfuse), otherwise the plain client. Optional:
    `pip install langfuse`; without it the app runs untraced and says so in the log."""
    if os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"):
        try:
            from langfuse.openai import OpenAI as TracedOpenAI
            log.info("LLM calls are traced to Langfuse.")
            return TracedOpenAI
        except ImportError:
            log.warning("Langfuse keys are set but the langfuse package is not installed.")
    return OpenAI


def build_llm_clients(s: Settings) -> tuple[OpenAI, OpenAI]:
    http = httpx.Client(trust_env=False, timeout=httpx.Timeout(45.0, connect=10.0))
    # One retry at most: a stalled provider should fail fast, not hold a request for minutes.
    chat = _client_class()(api_key=s.llm_api_key, base_url=s.llm_base_url, http_client=http,
                           max_retries=1)
    embed = OpenAI(api_key=s.llm_api_key, base_url=s.embed_base_url, http_client=http,
                   max_retries=1)
    return chat, embed


def build_self_rag(s: Settings, store: GraphStore, redis_client=None) -> SelfRAG:
    chat, embed = build_llm_clients(s)
    index = Pinecone(api_key=s.pinecone_api_key).Index(s.pinecone_index_name)
    retriever = Retriever(embed, index, s.embed_model, redis_client)
    return SelfRAG(retriever, store, LLM(chat), s.router_model, s.reasoning_model)


def build_trip_planner(s: Settings, store: GraphStore, redis_client=None, memory=None):
    from app.graph.persistence import make_checkpointer
    from app.graph.trip_graph import TripPlanner
    from mcp_server.client import MCPTools

    chat, embed = build_llm_clients(s)
    index = Pinecone(api_key=s.pinecone_api_key).Index(s.pinecone_index_name)
    retriever = Retriever(embed, index, s.embed_model, redis_client)
    return TripPlanner(LLM(chat), retriever, store, s.router_model, s.planner_model,
                       checkpointer=make_checkpointer(s.checkpoint_path, s.database_url),
                       tools=MCPTools(s.mcp_transport), concierge=s.concierge_enabled,
                       memory=memory)
