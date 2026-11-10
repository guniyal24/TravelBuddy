"""Settings tolerate the copy-paste mistakes hosting dashboards invite."""
from app.config import Settings


def test_keys_pasted_with_whitespace_are_cleaned(monkeypatch):
    monkeypatch.setenv("DEEPINFRA_API_KEY", "  di-key-123\n")
    monkeypatch.setenv("PINECONE_API_KEY", "pc-key\t")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db \n")
    s = Settings(secret_key="x" * 32, _env_file=None)
    assert s.llm_api_key == "di-key-123"
    assert s.pinecone_api_key == "pc-key"
    assert s.database_url == "postgresql://u:p@host/db"
