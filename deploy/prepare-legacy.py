#!/usr/bin/env python3
"""Safely stamp the pre-Alembic 0.1.0 schema before its first native update."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect

from noesis.persistence.models import Base

REVISION = "0001"
USER_VERSION = 1


def prepare(path: Path) -> None:
    if not path.exists() or path.stat().st_size == 0:
        return
    engine = create_engine(f"sqlite:///{path}")
    try:
        with engine.begin() as connection:
            inspector = inspect(connection)
            tables = set(inspector.get_table_names())
            if "alembic_version" in tables:
                return
            expected_tables = set(Base.metadata.tables)
            if not tables.intersection(expected_tables):
                return
            for name, table in Base.metadata.tables.items():
                if name not in tables:
                    raise RuntimeError(f"legacy database is missing table {name}")
                actual = {column["name"] for column in inspector.get_columns(name)}
                expected = {column.name for column in table.columns}
                if actual != expected:
                    raise RuntimeError(f"legacy database has incompatible table {name}")
            user_version = connection.exec_driver_sql("PRAGMA user_version").scalar()
            if user_version != USER_VERSION:
                raise RuntimeError(
                    f"legacy database user_version is {user_version}, expected {USER_VERSION}"
                )
            connection.exec_driver_sql(
                "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
            )
            connection.exec_driver_sql(
                "INSERT INTO alembic_version (version_num) VALUES (?)", (REVISION,)
            )
    finally:
        engine.dispose()
    with sqlite3.connect(path) as database:
        if database.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("legacy database failed integrity check after stamping")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} DATABASE")
    prepare(Path(sys.argv[1]))
