import threading

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from aos.config import get_settings
from aos.db.session import schema_lock

_saver: BaseCheckpointSaver | None = None
_pool = None
_lock = threading.Lock()


def postgres_conninfo(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def get_checkpointer() -> BaseCheckpointSaver:
    global _saver, _pool
    with _lock:
        if _saver is not None:
            return _saver
        settings = get_settings()
        if settings.storage_mode == "memory":
            _saver = InMemorySaver()
            return _saver

        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        _pool = ConnectionPool(
            conninfo=postgres_conninfo(settings.database_url),
            max_size=10,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
            open=True,
        )
        saver = PostgresSaver(_pool)
        with schema_lock():
            saver.setup()
        _saver = saver
        return _saver


def reset_checkpointer() -> None:
    global _saver, _pool
    with _lock:
        if _pool is not None:
            _pool.close()
        _saver = None
        _pool = None
