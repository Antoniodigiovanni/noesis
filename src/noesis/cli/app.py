from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import typer
from sqlalchemy import func, select, text

from noesis import __version__
from noesis.application.service import Noesis
from noesis.persistence.database import default_database_path
from noesis.application.common import add_event
from noesis.persistence.models import Assessment, CaptureProposal, KnowledgeUnit, MemoryState, RebuildFailure, ReviewSession
from noesis.scheduler.fsrs_adapter import FsrsAdapter


app = typer.Typer(no_args_is_help=True)


@app.command("init-db")
def init_db(database: Path | None = None):
    core = Noesis(database)
    typer.echo(str(core.db.engine.url.database))


@app.command()
def diagnose(database: Path | None = None):
    core = Noesis(database)
    with core.db.read() as session:
        integrity = session.execute(text("PRAGMA integrity_check")).scalar()
        schema = session.execute(text("PRAGMA user_version")).scalar()
        lifecycle = dict(session.execute(select(KnowledgeUnit.lifecycle_status, func.count()).group_by(KnowledgeUnit.lifecycle_status)).all())
        report = {
            "noesis_version": __version__, "schema_version": schema,
            "scheduler": FsrsAdapter.version, "database": str(core.db.engine.url.database),
            "database_health": integrity, "sqlite_version": sqlite3.sqlite_version,
            "lifecycle_counts": lifecycle,
            "pending_captures": session.scalar(select(func.count(CaptureProposal.id)).where(CaptureProposal.status == "pending")) or 0,
            "pending_disputes": session.scalar(select(func.count(Assessment.id)).where(Assessment.status.in_(("proposed", "disputed")))) or 0,
            "open_review_sessions": session.scalar(select(func.count(ReviewSession.id)).where(ReviewSession.status.in_(("created", "awaiting_question", "awaiting_answer", "awaiting_resolution")))) or 0,
            "failed_scheduler_rebuilds": session.scalar(select(func.count(RebuildFailure.id)).where(RebuildFailure.resolved.is_(False))) or 0,
            "mcp_startup_status": "schema initialized; use `hermes mcp test noesis` for protocol health",
        }
    typer.echo(json.dumps(report, indent=2, default=str))


@app.command("export")
def export_data(output: Path, database: Path | None = None):
    core = Noesis(database)
    export = {"format": "noesis-export-v1", "noesis_version": __version__, "tables": {}}
    with core.db.engine.connect() as connection:
        for table in core.db.engine.dialect.get_table_names(connection):
            if table.startswith("sqlite_"): continue
            rows = connection.exec_driver_sql(f'SELECT * FROM "{table}"').mappings().all()
            export["tables"][table] = [dict(row) for row in rows]
    output.write_text(json.dumps(export, indent=2, default=str), encoding="utf-8")
    typer.echo(str(output))


@app.command("delete-all")
def delete_all(confirm: str = typer.Option(..., help="Type DELETE-NOESIS to confirm"), database: Path | None = None):
    if confirm != "DELETE-NOESIS":
        raise typer.BadParameter("confirmation must exactly equal DELETE-NOESIS")
    path = (database or default_database_path()).expanduser().resolve()
    deleted = []
    for target in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        if target.exists():
            target.unlink()
            deleted.append(str(target))
    typer.echo(json.dumps({"deleted": deleted, "recoverable": False}))


@app.command("test-make-due", hidden=True)
def test_make_due(knowledge_unit_id: str, database: Path | None = None):
    """Acceptance-test fixture; unavailable unless explicitly enabled."""
    if os.environ.get("NOESIS_ENABLE_TEST_FIXTURES") != "1":
        raise typer.BadParameter("test fixtures are disabled; set NOESIS_ENABLE_TEST_FIXTURES=1 explicitly")
    core = Noesis(database)
    with core.db.transaction() as session:
        unit = session.get(KnowledgeUnit, knowledge_unit_id)
        if unit is None:
            raise typer.BadParameter("knowledge unit not found")
        memory = session.scalar(select(MemoryState).where(MemoryState.learner_id == unit.learner_id, MemoryState.knowledge_unit_id == unit.id))
        due_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        if memory is None:
            memory = MemoryState(learner_id=unit.learner_id, knowledge_unit_id=unit.id, scheduler_state={}, scheduler_version="test-fixture", next_due_at=due_at)
            session.add(memory)
        else:
            memory.next_due_at = due_at
        add_event(session, aggregate_type="memory_state", aggregate_id=unit.id, event_type="test_fixture.made_due", actor="test-fixture", correlation_id="test-fixture", payload={"next_due_at": due_at.isoformat()})
    typer.echo(json.dumps({"knowledge_unit_id": knowledge_unit_id, "next_due_at": due_at.isoformat(), "test_only": True}))


if __name__ == "__main__":
    app()
