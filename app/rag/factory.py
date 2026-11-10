"""Build real RAG components from Settings (shared by the API and the eval harness)."""
import httpx
from openai import OpenAI
from pinecone import Pinecone

from app.config import Settings
from app.db.graph import GraphStore
from app.rag.llm import LLM
from app.rag.retriever import Retriever
from app.rag.self_rag import SelfRAG


def build_llm_clients(s: Settings) -> tuple[OpenAI, OpenAI]:
    http = httpx.Client(trust_env=False, timeout=httpx.Timeout(45.0, connect=10.0))
    # One retry at most: a stalled provider should fail fast, not hold a request for minutes.
    chat = OpenAI(api_key=s.llm_api_key, base_url=s.llm_base_url, http_client=http,
                  max_retries=1)
    embed = OpenAI(api_key=s.llm_api_key, base_url=s.embed_base_url, http_client=http,
                   max_retries=1)
    return chat, embed


def build_self_rag(s: Settings, store: GraphStore, redis_client=None) -> SelfRAG:
    chat, embed = build_llm_clients(s)
    index = Pinecone(api_key=s.pinecone_api_key).Index(s.pinecone_index_name)
    retriever = Retriever(embed, index, s.embed_model, redis_client)
    return SelfRAG(retriever, store, LLM(chat), s.router_model, s.reasoning_model)


def build_trip_planner(s: Settings, store: GraphStore, redis_client=None):
    from app.graph.persistence import make_checkpointer
    from app.graph.trip_graph import TripPlanner
    from mcp_server.client import MCPTools

    chat, embed = build_llm_clients(s)
    index = Pinecone(api_key=s.pinecone_api_key).Index(s.pinecone_index_name)
    retriever = Retriever(embed, index, s.embed_model, redis_client)
    return TripPlanner(LLM(chat), retriever, store, s.router_model, s.planner_model,
                       checkpointer=make_checkpointer(s.checkpoint_path, s.database_url),
                       tools=MCPTools(s.mcp_transport), concierge=s.concierge_enabled)
