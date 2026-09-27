from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from noesis.application.common import now_utc
from noesis.application.contracts import AssessmentInput, ExerciseSpecInput
from noesis.domain.errors import Conflict
from noesis.persistence.models import (
    Assessment,
    Attempt,
    Event,
    KnowledgeUnit,
    MemoryState,
    ReviewSession,
    SchedulerTransition,
)
from test_vertical_slice import capture


def assessment(outcome="successful", confidence=0.99):
    return AssessmentInput(
        recall_outcome=outcome,
        evidence=["test evidence"],
        missing_elements=[],
        assessor_confidence=confidence,
        model_id="test:model",
        rubric_version="test-v1",
    )


def ask_and_answer(core, review_id, suffix, *, outcome="successful", confidence=0.99):
    question = core.reviews.start(
        session_id=review_id,
        question_text=f"Question {suffix}?",
        idempotency_key=f"question-{suffix}",
    )
    submitted = core.reviews.submit(
        review_session_id=review_id,
        exact_response=f"Answer {suffix}",
        assessment=assessment(outcome, confidence),
        idempotency_key=f"answer-{suffix}",
    )
    return question, submitted


def test_resolving_dispute_for_accepted_attempt_does_not_skip_current_item(core):
    capture(core)
    review = core.reviews.start(idempotency_key="start")
    _, first = ask_and_answer(core, review["review_session_id"], "one")
    second_question = core.reviews.start(
        session_id=review["review_session_id"],
        question_text="Question two?",
        idempotency_key="question-two",
    )

    disputed = core.learning.resolve(
        action="dispute_assessment",
        assessment_id=first["assessment_id"],
        idempotency_key="dispute-first",
    )
    assert disputed["review_status"] == "awaiting_answer"
    resolved = core.learning.resolve(
        action="accept_self_grade",
        assessment_id=first["assessment_id"],
        self_grade="difficult",
        idempotency_key="resolve-first",
    )
    assert resolved["review_status"] == "awaiting_answer"

    with core.db.read() as session:
        row = session.get(ReviewSession, review["review_session_id"])
        assert row.current_position == 1
        assert row.current_exercise_instance_id == second_question["current_exercise_instance_id"]


def test_expired_review_rejects_attempt_without_recording_evidence(core):
    capture(core)
    review = core.reviews.start(idempotency_key="expiry-start")
    core.reviews.start(
        session_id=review["review_session_id"],
        question_text="An expiring question?",
        idempotency_key="expiry-question",
    )
    with core.db.transaction() as session:
        session.get(ReviewSession, review["review_session_id"]).expires_at = now_utc() - timedelta(seconds=1)

    with pytest.raises(Conflict, match="expired"):
        core.reviews.submit(
            review_session_id=review["review_session_id"],
            exact_response="Too late",
            assessment=assessment(),
            idempotency_key="expired-answer",
        )

    with core.db.read() as session:
        row = session.get(ReviewSession, review["review_session_id"])
        assert row.status == "expired"
        assert session.scalar(select(func.count(Attempt.id))) == 0
        assert session.scalar(select(func.count(Assessment.id))) == 0
        assert session.scalar(select(func.count(SchedulerTransition.id))) == 0
        assert session.scalar(select(func.count(MemoryState.id))) == 0
        assert session.scalar(
            select(func.count(Event.id)).where(
                Event.aggregate_id == row.id, Event.event_type == "review.expired"
            )
        ) == 1


def test_invalidating_completed_attempt_queues_a_reviewable_retry(core):
    capture(core)
    review = core.reviews.start(idempotency_key="retry-start")
    _, first = ask_and_answer(core, review["review_session_id"], "retry-one")
    ask_and_answer(core, review["review_session_id"], "retry-two")

    result = core.learning.resolve(
        action="ambiguous_question",
        attempt_id=first["attempt_id"],
        idempotency_key="invalidate-first",
    )
    assert result["review_status"] == "awaiting_question"
    resumed = core.reviews.start(
        session_id=review["review_session_id"],
        question_text="Retry the invalid item?",
        idempotency_key="retry-question",
    )
    assert resumed["status"] == "awaiting_answer"
    assert resumed["current_position"] == 2
    assert resumed["item_count"] == 3


def test_resolved_failed_grade_reactivates_maintenance_unit(core):
    _, committed = capture(core)
    target, other = committed["created"]["knowledge_units"]
    core.learning.update_state(
        knowledge_unit_id=target,
        lifecycle_status="maintenance",
        idempotency_key="maintenance",
    )
    core.learning.update_state(
        knowledge_unit_id=other,
        lifecycle_status="suspended",
        idempotency_key="suspend-other",
    )
    with core.db.transaction() as session:
        session.get(KnowledgeUnit, target).updated_at = now_utc() - timedelta(days=100)
    review = core.reviews.start(idempotency_key="maintenance-start")
    _, submitted = ask_and_answer(
        core,
        review["review_session_id"],
        "maintenance",
        outcome="failed",
        confidence=0.1,
    )
    assert submitted["assessment_status"] == "proposed"

    core.learning.resolve(
        action="accept_self_grade",
        assessment_id=submitted["assessment_id"],
        self_grade="failed",
        idempotency_key="maintenance-resolve",
    )
    with core.db.read() as session:
        assert session.get(KnowledgeUnit, target).lifecycle_status == "active"
        assert session.scalar(
            select(MemoryState).where(MemoryState.knowledge_unit_id == target)
        ) is not None


def test_correcting_unit_advances_version_and_rejects_stale_update(core):
    capture(core)
    review = core.reviews.start(idempotency_key="correction-start")
    _, submitted = ask_and_answer(core, review["review_session_id"], "correction")
    with core.db.read() as session:
        attempt = session.get(Attempt, submitted["attempt_id"])
        unit = session.get(KnowledgeUnit, attempt.knowledge_unit_id)
        old_version = unit.version
        old_updated_at = unit.updated_at

    corrected = core.learning.resolve(
        action="correct_knowledge_unit",
        attempt_id=submitted["attempt_id"],
        corrected_statement="A corrected canonical statement.",
        exercise=ExerciseSpecInput(
            exercise_type="free_recall",
            required_elements=["corrected statement"],
            acceptable_alternatives=[],
            common_errors=[],
            difficulty_target=0.5,
        ),
        idempotency_key="correct-unit",
    )
    assert corrected["version"] == old_version + 1
    with pytest.raises(Conflict, match="version conflict"):
        core.learning.update_state(
            knowledge_unit_id=corrected["knowledge_unit_id"],
            importance=0.8,
            expected_version=old_version,
            idempotency_key="stale-after-correction",
        )
    with core.db.read() as session:
        unit = session.get(KnowledgeUnit, corrected["knowledge_unit_id"])
        assert unit.updated_at > old_updated_at
