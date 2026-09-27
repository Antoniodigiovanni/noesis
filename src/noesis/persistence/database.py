from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session, sessionmaker

from noesis.persistence.models import Base


def default_database_path() -> Path:
    configured = os.environ.get("NOESIS_DB_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path.home() / ".local" / "share" / "noesis" / "noesis.db"


SCHEMA_REVISION = "0001"
SCHEMA_USER_VERSION = 1


def _secure_database_files(db_path: Path) -> None:
    for candidate in (db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")):
        if candidate.exists():
            candidate.chmod(0o600)


def create_database_engine(path: str | Path | None = None) -> Engine:
    db_path = Path(path) if path else default_database_path()
    if not db_path.parent.exists():
        db_path.parent.mkdir(parents=True, mode=0o700)
    if not db_path.exists():
        descriptor = os.open(db_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        os.close(descriptor)
    _secure_database_files(db_path)
    engine = create_engine(f"sqlite:///{db_path}", future=True)

    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()
        _secure_database_files(db_path)

    return engine


class Database:
    def __init__(self, path: str | Path | None = None) -> None:
        self.engine = create_database_engine(path)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def create_schema(self) -> None:
        with self.engine.begin() as connection:
            tables = set(inspect(connection).get_table_names())
            application_tables = set(Base.metadata.tables)
            if not tables.intersection(application_tables):
                Base.metadata.create_all(connection)
                self._create_fts(connection)
                connection.exec_driver_sql(
                    "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
                )
                connection.exec_driver_sql(
                    "INSERT INTO alembic_version (version_num) VALUES (?)",
                    (SCHEMA_REVISION,),
                )
                return
            self._validate_schema(connection)
            if "alembic_version" not in tables:
                # Databases created by Noesis 0.1.0 before migration tracking used
                # the same schema. Stamp only after exact structural validation.
                connection.exec_driver_sql(
                    "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
                )
                connection.exec_driver_sql(
                    "INSERT INTO alembic_version (version_num) VALUES (?)",
                    (SCHEMA_REVISION,),
                )

    @staticmethod
    def _create_fts(connection: Connection) -> None:
        connection.exec_driver_sql(f"PRAGMA user_version={SCHEMA_USER_VERSION}")
        connection.exec_driver_sql(
            "CREATE VIRTUAL TABLE IF NOT EXISTS learning_fts USING fts5("
            "entity_type UNINDEXED, entity_id UNINDEXED, learner_id UNINDEXED, title, body, provenance)"
        )

    @staticmethod
    def _validate_schema(connection: Connection) -> None:
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        for name, table in Base.metadata.tables.items():
            if name not in tables:
                raise RuntimeError(f"database schema is incomplete: missing table {name}; run Alembic migrations")
            actual_columns = {column["name"] for column in inspector.get_columns(name)}
            expected_columns = {column.name for column in table.columns}
            if actual_columns != expected_columns:
                raise RuntimeError(f"database schema is incompatible at table {name}; run Alembic migrations")
        if "alembic_version" in tables:
            revisions = connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalars().all()
            if revisions != [SCHEMA_REVISION]:
                raise RuntimeError(
                    f"database revision {revisions!r} is incompatible with expected revision {SCHEMA_REVISION}; run Alembic migrations"
                )
        user_version = connection.exec_driver_sql("PRAGMA user_version").scalar()
        if user_version != SCHEMA_USER_VERSION:
            raise RuntimeError(
                f"database user_version {user_version} is incompatible with expected version {SCHEMA_USER_VERSION}"
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
