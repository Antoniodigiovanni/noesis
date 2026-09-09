from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from noesis.persistence.models import Base


def default_database_path() -> Path:
    configured = os.environ.get("NOESIS_DB_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path.home() / ".local" / "share" / "noesis" / "noesis.db"


def create_database_engine(path: str | Path | None = None) -> Engine:
    db_path = Path(path) if path else default_database_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", future=True)

    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return engine


class Database:
    def __init__(self, path: str | Path | None = None) -> None:
        self.engine = create_database_engine(path)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)
        self._create_fts()

    def _create_fts(self) -> None:
        with self.engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA user_version=1")
            connection.exec_driver_sql(
                "CREATE VIRTUAL TABLE IF NOT EXISTS learning_fts USING fts5("
                "entity_type UNINDEXED, entity_id UNINDEXED, learner_id UNINDEXED, title, body, provenance)"
            )

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        with self.sessions() as session:
            try:
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    @contextmanager
    def read(self) -> Iterator[Session]:
        with self.sessions() as session:
            yield session
