"""Checkpointer construction for workflow state persistence.

We use LangGraph's SQLite checkpointer so that a plan's state — including the
human-in-the-loop pause — persists across API restarts. If SQLite is somehow
unavailable we fall back to an in-memory saver (state lost on restart).
"""

from __future__ import annotations

from pathlib import Path

from app.config import Settings


def build_checkpointer(settings: Settings):
    """Return a LangGraph checkpointer (SQLite by default).

    The newer ``SqliteSaver`` caches a raw sqlite connection opened with
    ``check_same_thread=False``. We keep our own long-lived connection so the
    saver (and the compiled graph) can be shared across threads/restarts; the
    WorkflowManager serializes access with a per-plan lock.
    """
    try:
        import sqlite3

        from langgraph.checkpoint.sqlite import SqliteSaver

        path = Path(settings.database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), check_same_thread=False)
        saver = SqliteSaver(conn)
        return saver
    except (ImportError, OSError) as exc:  # pragma: no cover - defensive
        try:
            from langgraph.checkpoint.memory import InMemorySaver

            saver = InMemorySaver()
        except ImportError:
            from langgraph.checkpoint.memory import MemorySaver

            saver = MemorySaver()
        print(f"WARNING: SQLite saver unavailable ({exc}); using in-memory saver.")
        return saver