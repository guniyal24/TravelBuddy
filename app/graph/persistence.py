"""Durable trip state. A trip paused at a human decision survives a server restart.

  DATABASE_URL set   Postgres (e.g. a free Neon database). Survives redeploys and works with
                     several API instances. The checkpoint tables are created on first start.
  otherwise          SQLite file at CHECKPOINT_PATH. Fine locally; on hosts with ephemeral
                     disks (Render free tier) it is lost on every redeploy.
"""
import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver


def is_postgres(url: str) -> bool:
    return url.startswith(("postgres://", "postgresql://"))


def make_pg_pool(url: str, max_size: int = 5):
    """A small connection pool. prepare_threshold=0 keeps it compatible with pooled
    (PgBouncer) endpoints such as Neon's '-pooler' host."""
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    return ConnectionPool(url, min_size=1, max_size=max_size, open=True, kwargs={
        "autocommit": True, "prepare_threshold": 0, "row_factory": dict_row})


def make_checkpointer(path: str, database_url: str = ""):
    if database_url and is_postgres(database_url):
        from langgraph.checkpoint.postgres import PostgresSaver

        saver = PostgresSaver(make_pg_pool(database_url))
        saver.setup()  # idempotent: creates or migrates the checkpoint tables
        return saver
    if path != ":memory:":
        Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
    # The API calls the planner from worker threads; SqliteSaver serialises access itself.
    conn = sqlite3.connect(path, check_same_thread=False)
    return SqliteSaver(conn)


def close_checkpointer(saver) -> None:
    """Release the Postgres pool (SQLite needs nothing)."""
    pool = getattr(saver, "conn", None)
    if pool is not None and hasattr(pool, "close") and not isinstance(pool, sqlite3.Connection):
        pool.close()
