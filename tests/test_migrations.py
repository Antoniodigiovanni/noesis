import os
import subprocess

from sqlalchemy import create_engine, inspect, text


def test_initial_alembic_migration(tmp_path):
    database = tmp_path / "migrated.db"
    env = {**os.environ, "NOESIS_DB_PATH": str(database)}
    subprocess.run([".venv/bin/alembic", "upgrade", "head"], check=True, env=env, cwd=os.getcwd(), capture_output=True, text=True)
    engine = create_engine(f"sqlite:///{database}")
    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        assert {"sources", "knowledge_units", "attempts", "events", "alembic_version"} <= tables
        assert connection.execute(text("PRAGMA user_version")).scalar() == 1
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0001"
