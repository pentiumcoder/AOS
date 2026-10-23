import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from aos.config import get_settings
from aos.db.models import Base

_engine: Engine | None = None
_sessionmaker: sessionmaker[Session] | None = None


def database_url() -> str:
    settings = get_settings()
    if settings.storage_mode == "services" or settings.database_url.startswith("sqlite"):
        return settings.database_url
    path = os.path.join(tempfile.gettempdir(), f"aos-{os.getpid()}.sqlite")
    return f"sqlite:///{path}"


def is_sqlite() -> bool:
    return database_url().startswith("sqlite")


def get_engine() -> Engine:
    global _engine, _sessionmaker
    if _engine is None:
        url = database_url()
        kwargs = {"connect_args": {"timeout": 30}} if url.startswith("sqlite") else {}
        _engine = create_engine(url, pool_pre_ping=True, **kwargs)
        _sessionmaker = sessionmaker(_engine, expire_on_commit=False)
    return _engine


@contextmanager
def session_scope() -> Iterator[Session]:
    get_engine()
    assert _sessionmaker is not None
    session = _sessionmaker()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    Base.metadata.create_all(get_engine())


def reset_db() -> None:
    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def ping() -> bool:
    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))
    return True


def dispose() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _sessionmaker = None
