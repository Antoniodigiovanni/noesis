from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from noesis.application.contracts import AssessmentInput
from noesis.application.service import Noesis
from noesis.cli.app import diagnose, export_data
from noesis.persistence.models import AssessmentStatusEvent, Base
from test_vertical_slice import capture


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_new_database_and_parent_are_private_and_migration_tracked(tmp_path):
    parent = tmp_path / "private-state"
    database = parent / "noesis.db"
    previous = os.umask(0)
    try:
        core = Noesis(database)
    finally:
        os.umask(previous)
    assert mode(parent) == 0o700
    assert mode(database) == 0o600
    with core.db.engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == "0001"


def test_database_sidecars_are_private_in_an_existing_shared_parent(tmp_path):
    parent = tmp_path / "existing"
    parent.mkdir(mode=0o755)
    database = parent / "noesis.db"
    previous = os.umask(0)
    try:
        core = Noesis(database)
        with core.db.transaction():
            pass
    finally:
        os.umask(previous)
    assert mode(parent) == 0o755
    for candidate in (database, Path(f"{database}-wal"), Path(f"{database}-shm")):
        assert mode(candidate) == 0o600


def test_legacy_initial_schema_is_stamped_only_after_validation(tmp_path):
    database = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        Base.metadata.create_all(connection)
        connection.exec_driver_sql(
            "CREATE VIRTUAL TABLE learning_fts USING fts5("
            "entity_type UNINDEXED, entity_id UNINDEXED, learner_id UNINDEXED, title, body, provenance)"
        )
        connection.exec_driver_sql("PRAGMA user_version=1")
    engine.dispose()

    core = Noesis(database)
    with core.db.engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == "0001"


def test_incomplete_existing_schema_is_rejected_instead_of_masked(tmp_path):
    database = tmp_path / "broken.db"
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE knowledge_units (id VARCHAR(36) PRIMARY KEY)")
        connection.exec_driver_sql("PRAGMA user_version=1")
    engine.dispose()

    with pytest.raises(RuntimeError, match="missing table"):
        Noesis(database)


def test_export_is_private_even_with_permissive_umask(core, tmp_path):
    output = tmp_path / "learning-export.json"
    previous = os.umask(0)
    try:
        export_data(output, database=core.db.engine.url.database)
    finally:
        os.umask(previous)
    assert mode(output) == 0o600
    assert json.loads(output.read_text(encoding="utf-8"))["format"] == "noesis-export-v1"


def test_export_refuses_to_follow_a_symlink(core, tmp_path):
    protected = tmp_path / "protected.txt"
    protected.write_text("keep", encoding="utf-8")
    link = tmp_path / "export.json"
    link.symlink_to(protected)
    with pytest.raises(OSError):
        export_data(link, database=core.db.engine.url.database)
    assert protected.read_text(encoding="utf-8") == "keep"


def test_diagnose_counts_latest_assessment_status(core, capsys):
    capture(core)
    review = core.reviews.start(idempotency_key="diagnose-start")
    core.reviews.start(
        session_id=review["review_session_id"],
        question_text="First?",
        idempotency_key="diagnose-question-1",
    )
    first = core.reviews.submit(
        review_session_id=review["review_session_id"],
        exact_response="First answer",
        assessment=AssessmentInput(
            recall_outcome="successful",
            evidence=[],
            missing_elements=[],
            assessor_confidence=0.99,
            model_id="test:model",
            rubric_version="v1",
        ),
        idempotency_key="diagnose-answer-1",
    )
    core.reviews.start(
        session_id=review["review_session_id"],
        question_text="Second?",
        idempotency_key="diagnose-question-2",
    )
    second = core.reviews.submit(
        review_session_id=review["review_session_id"],
        exact_response="Second answer",
        assessment=AssessmentInput(
            recall_outcome="difficult",
            evidence=[],
            missing_elements=[],
            assessor_confidence=0.1,
            model_id="test:model",
            rubric_version="v1",
        ),
        idempotency_key="diagnose-answer-2",
    )
    with core.db.transaction() as session:
        session.add(AssessmentStatusEvent(assessment_id=first["assessment_id"], status="disputed", actor="user"))
        session.add(AssessmentStatusEvent(assessment_id=second["assessment_id"], status="superseded", actor="user"))

    diagnose(database=Path(core.db.engine.url.database))
    report = json.loads(capsys.readouterr().out)
    assert report["pending_disputes"] == 1
