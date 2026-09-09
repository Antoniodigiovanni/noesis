from copy import deepcopy
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from noesis.application.contracts import AssessmentInput, CaptureProposalInput
from noesis.domain.errors import Conflict
from noesis.cli.app import test_make_due as make_due_fixture
from noesis.persistence.models import KnowledgeUnit, MemoryState, ReviewSession
from noesis.application.common import now_utc
from test_vertical_slice import capture, meditations_payload


def test_idempotency_key_conflicts_on_changed_request(core):
    core.capture.propose(CaptureProposalInput.model_validate(meditations_payload()), actor="hermes", idempotency_key="same")
    changed = meditations_payload("Different source content")
    with pytest.raises(Conflict):
        core.capture.propose(CaptureProposalInput.model_validate(changed), actor="hermes", idempotency_key="same")


def test_exact_and_lexical_duplicate_detection(core):
    capture(core)
    exact = core.capture.propose(CaptureProposalInput.model_validate(meditations_payload()), actor="hermes", idempotency_key="exact-duplicate")
    assert any(match["kind"] == "exact" and match["item_type"] == "source" for match in exact["duplicates"])
    assert any(match["kind"] == "exact" and match["item_type"] == "knowledge_unit" for match in exact["duplicates"])
    lexical_payload = meditations_payload("Fresh excerpt about responding deliberately to choices made by other people.")
    lexical_payload["knowledge_units"][0]["canonical_statement"] = "A deliberate response remains ours even when choices made by other people are uncontrollable."
    lexical = core.capture.propose(CaptureProposalInput.model_validate(lexical_payload), actor="hermes", idempotency_key="lexical-duplicate")
    assert any(match["kind"] == "lexical" for match in lexical["duplicates"])


def test_lifecycle_suspend_resume_and_optimistic_conflict(core):
    _, result = capture(core)
    unit_id = result["created"]["knowledge_units"][0]
    suspended = core.learning.update_state(knowledge_unit_id=unit_id, lifecycle_status="suspended", expected_version=1, idempotency_key="suspend")
    assert suspended["lifecycle_status"] == "suspended"
    with pytest.raises(Conflict):
        core.learning.update_state(knowledge_unit_id=unit_id, lifecycle_status="active", expected_version=1, idempotency_key="stale")
    resumed = core.learning.update_state(knowledge_unit_id=unit_id, lifecycle_status="active", expected_version=2, idempotency_key="resume")
    assert resumed["lifecycle_status"] == "active"


def test_policy_budget_and_review_expiry(core):
    capture(core)
    result = core.learning.update_state(learner_id="default", policy_updates={"daily_item_budget": 1}, idempotency_key="policy")
    assert result["policy"]["daily_item_budget"] == 1
    review = core.reviews.start(learner_id="default", idempotency_key="start-budget")
    assert review["item_count"] == 1
    with core.db.transaction() as session:
        row = session.get(ReviewSession, review["review_session_id"])
        row.expires_at = row.created_at
    new_review = core.reviews.start(learner_id="default", idempotency_key="after-expiry")
    assert new_review["review_session_id"] != review["review_session_id"]
    with core.db.read() as session:
        assert session.get(ReviewSession, review["review_session_id"]).status == "expired"


def test_failed_maintenance_probe_reactivates_without_erasing_memory(core):
    _, result = capture(core)
    unit_id = result["created"]["knowledge_units"][0]
    core.learning.update_state(knowledge_unit_id=unit_id, lifecycle_status="maintenance", idempotency_key="maintenance")
    with core.db.transaction() as session:
        session.get(KnowledgeUnit, unit_id).updated_at = now_utc() - timedelta(days=100)
    review = core.reviews.start(learner_id="default", idempotency_key="maintenance-review")
    question = core.reviews.start(learner_id="default", session_id=review["review_session_id"], question_text="Explain the distinction.", idempotency_key="maintenance-question")
    assessment = AssessmentInput(recall_outcome="failed", evidence=[], missing_elements=["distinction"], assessor_confidence=0.99, model_id="test:model", rubric_version="v1")
    submitted = core.reviews.submit(review_session_id=review["review_session_id"], exact_response="I do not remember.", assessment=assessment, idempotency_key="maintenance-attempt")
    assert submitted["scheduler_update"]
    with core.db.read() as session:
        unit = session.get(KnowledgeUnit, unit_id)
        memory = session.scalar(select(MemoryState).where(MemoryState.knowledge_unit_id == unit_id))
        assert unit.lifecycle_status == "active"
        assert memory.scheduler_state


def test_sqlite_rejects_overlapping_immediate_writers(core):
    first = core.db.engine.connect()
    second = core.db.engine.connect()
    try:
        first.exec_driver_sql("BEGIN IMMEDIATE")
        second.exec_driver_sql("PRAGMA busy_timeout=10")
        with pytest.raises(OperationalError):
            second.exec_driver_sql("BEGIN IMMEDIATE")
    finally:
        first.rollback()
        second.rollback()
        first.close()
        second.close()


def test_due_fixture_is_explicitly_gated(core, monkeypatch):
    _, result = capture(core)
    unit_id = result["created"]["knowledge_units"][0]
    database = core.db.engine.url.database
    monkeypatch.delenv("NOESIS_ENABLE_TEST_FIXTURES", raising=False)
    with pytest.raises(Exception, match="test fixtures are disabled"):
        make_due_fixture(unit_id, database=database)
    monkeypatch.setenv("NOESIS_ENABLE_TEST_FIXTURES", "1")
    make_due_fixture(unit_id, database=database)
    with core.db.read() as session:
        assert session.scalar(select(MemoryState).where(MemoryState.knowledge_unit_id == unit_id)).scheduler_version == "test-fixture"
