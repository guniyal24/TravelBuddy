"""Durable trip state. A trip paused at a human decision survives a server restart.

SQLite (file) is used by default. On hosts with ephemeral disks (e.g. Render free tier) the
file is lost on redeploy unless a persistent disk is mounted at the checkpoint path; for
multi-instance deployments use a shared database instead (a Postgres checkpointer is the
natural next step and is not implemented here).
"""
import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver


def make_checkpointer(path: str) -> SqliteSaver:
    if path != ":memory:":
        Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
    # The API calls the planner from worker threads; SqliteSaver serialises access itself.
    conn = sqlite3.connect(path, check_same_thread=False)
    return SqliteSaver(conn)
