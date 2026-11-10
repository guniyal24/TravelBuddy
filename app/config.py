"""Central settings. All configuration comes from environment variables / .env."""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Auth. No default on purpose: the app must fail fast if it is missing.
    secret_key: str = Field(min_length=16)
    access_token_expire_minutes: int = 30
    jwt_algorithm: str = "HS256"

    # LLM / retrieval
    # LLM + embeddings go through OpenAI-compatible endpoints (DeepInfra by default).
    deepinfra_api_key: str = ""
    openai_api_key: str = ""
    llm_base_url: str = "https://api.deepinfra.com/v1/openai"
    embed_base_url: str = "https://api.deepinfra.com/v1/openai"
    pinecone_api_key: str = ""
    pinecone_index_name: str = "uttarakhand-planner"
    pinecone_vector_dim: int = 1024  # must match embed_model (bge-m3 = 1024)

    neo4j_uri: str = ""
    neo4j_user: str = ""
    neo4j_password: str = ""
    neo4j_database: str = "neo4j"

    embed_model: str = "BAAI/bge-m3"
    router_model: str = "mistralai/Mistral-Small-3.2-24B-Instruct-2506"
    chat_model: str = "meta-llama/Meta-Llama-3.1-8B-Instruct"
    # reasoning/planner: fast Mistral-Small; judge: pinned 70B so eval scores stay comparable
    reasoning_model: str = "mistralai/Mistral-Small-3.2-24B-Instruct-2506"
    judge_model: str = "meta-llama/Llama-3.3-70B-Instruct-Turbo"
    # Eval jury (judge v2): three model families, none from the generator's (Mistral) family,
    # so no judge grades its own family's writing. Pinned so scores stay comparable over time.
    judge_jury: str = ("meta-llama/Llama-3.3-70B-Instruct-Turbo,Qwen/Qwen2.5-72B-Instruct,"
                       "google/gemma-3-27b-it")
    judge_samples: int = 3  # verdicts sampled per juror (majority vote)
    judge_temperature: float = 0.7  # sampling temperature for those verdicts
    planner_model: str = "mistralai/Mistral-Small-3.2-24B-Instruct-2506"

    # Redis (cache + rate limit)
    redis_host: str = "localhost"
    redis_port: int = 6379
    rate_limit_per_minute: int = 10
    # Guest mode: try the app without an account. Guests get a stricter limit and a token that
    # expires; new guest sessions are limited per IP so the LLM bill stays bounded.
    guest_enabled: bool = True
    guest_rate_limit_per_minute: int = 5
    guest_token_expire_minutes: int = 24 * 60
    guest_sessions_per_ip_per_hour: int = 10
    guest_sessions_per_day: int = 300  # global cap: holds even if a client spoofs its IP
    # Postgres URL (e.g. Neon). When set, trip state, saved trips and profiles live there and
    # survive redeploys; the two SQLite paths below are then unused.
    database_url: str = ""
    checkpoint_path: str = "data/checkpoints.sqlite"  # durable trip state
    trips_path: str = "data/trips.sqlite"  # saved trips, profiles, checklist state
    mcp_transport: str = "memory"  # "memory" (in-process MCP) or "stdio" (subprocess server)
    rag_mode: str = "self"  # "self" (Self-RAG graph) or "hybrid" (prototype pipeline)

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def llm_api_key(self) -> str:
        return self.deepinfra_api_key or self.openai_api_key

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
