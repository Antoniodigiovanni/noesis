from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select

from noesis.application.common import add_event, get_idempotent, now_utc, policy_for, save_idempotent
from noesis.application.contracts import AssessmentInput, ExerciseSpecInput
from noesis.application.reviews import OUTCOME_GRADES
from noesis.domain.errors import Conflict, NotFound, ValidationFailure
from noesis.persistence.database import Database
from noesis.persistence.models import (
    Assessment, AssessmentStatusEvent, Attempt, AttemptValidityEvent, ExerciseInstance, ExerciseSpecification, KnowledgeUnit,
    KnowledgeUnitRevision, KnowledgeUnitSource, MemoryState, ReviewSession, SchedulerTransition,
)
from noesis.retrieval.indexing import index_document
from noesis.scheduler.fsrs_adapter import FsrsAdapter
from noesis.scheduler.rebuild import rebuild_memory_state


class LearningService:
    def __init__(self, db: Database, scheduler=None) -> None:
        self.db = db
        self.scheduler = scheduler or FsrsAdapter()

    def resolve(self, *, action: str, assessment_id: str | None = None, attempt_id: str | None = None,
                replacement: AssessmentInput | None = None, self_grade: str | None = None,
                corrected_statement: str | None = None, exercise: ExerciseSpecInput | None = None,
                actor: str = "user", correlation_id: str | None = None, idempotency_key: str) -> dict:
        if not idempotency_key.strip():
            raise ValidationFailure("idempotency_key must not be empty")
        correlation_id = correlation_id or str(uuid4())
        request = {"action": action, "assessment_id": assessment_id, "attempt_id": attempt_id,
                   "replacement": replacement.model_dump(mode="json") if replacement else None,
                   "self_grade": self_grade, "corrected_statement": corrected_statement,
                   "exercise": exercise.model_dump(mode="json") if exercise else None}
        with self.db.transaction() as session:
            cached = get_idempotent(session, "resolve_learning_issue", idempotency_key, request)
            if cached is not None:
                return cached
            if action == "dispute_assessment":
                assessment = self._assessment(session, assessment_id)
                current_status = self._assessment_status(session, assessment.id)
                if current_status not in ("accepted", "proposed"):
                    raise Conflict(f"assessment is {current_status}, not accepted or proposed")
                session.add(AssessmentStatusEvent(assessment_id=assessment.id, status="disputed", reason="User disputed grading", actor=actor))
                attempt = session.get(Attempt, assessment.attempt_id)
                review = session.get(ReviewSession, attempt.review_session_id)
                if self._is_current_attempt(review, attempt):
                    review.status = "awaiting_resolution"
                self._rebuild(session, review.learner_id, attempt.knowledge_unit_id)
                response = {"assessment_id": assessment.id, "status": "disputed", "review_status": review.status}
            elif action in ("replace_assessment", "accept_self_grade"):
                original = self._assessment(session, assessment_id)
                current_status = self._assessment_status(session, original.id)
                if current_status not in ("disputed", "proposed"):
                    raise Conflict(f"assessment is {current_status}, not disputed or proposed")
                attempt = session.get(Attempt, original.attempt_id)
                review = session.get(ReviewSession, attempt.review_session_id)
                if action == "accept_self_grade":
                    if self_grade not in OUTCOME_GRADES:
                        raise ValidationFailure("self_grade must be failed, difficult, successful, or effortless")
                    replacement = AssessmentInput(recall_outcome=self_grade, evidence=["User supplied self-grade"], missing_elements=[], assessor_confidence=1, user_confidence=1, model_id="user:self-grade", rubric_version="self-grade-v1")
                if replacement is None or replacement.recall_outcome == "ungradable":
                    raise ValidationFailure("a gradable replacement assessment is required")
                session.add(AssessmentStatusEvent(assessment_id=original.id, status="superseded", reason="Replacement assessment accepted", actor=actor))
                new = Assessment(attempt_id=attempt.id, recall_outcome=replacement.recall_outcome, evidence=replacement.evidence, missing_elements=replacement.missing_elements, possible_misconception=replacement.possible_misconception, assessor_confidence=replacement.assessor_confidence, user_confidence=replacement.user_confidence, model_id=replacement.model_id, rubric_version=replacement.rubric_version, status="accepted", supersedes_assessment_id=original.id)
                session.add(new); session.flush()
                session.add(AssessmentStatusEvent(assessment_id=new.id, status="accepted", actor=actor))
                unit = session.get(KnowledgeUnit, attempt.knowledge_unit_id)
                grade = OUTCOME_GRADES[replacement.recall_outcome]
                session.add(SchedulerTransition(learner_id=review.learner_id, knowledge_unit_id=unit.id, assessment_id=new.id, grade=grade, desired_retention=unit.desired_retention, scheduler_version=self.scheduler.version, input_state={}, output_state={}, reviewed_at=attempt.created_at, next_due_at=attempt.created_at, active=True, explanation={"resolution": action}))
                memory = self._rebuild(session, review.learner_id, unit.id)
                if grade == 1 and unit.lifecycle_status == "maintenance":
                    unit.lifecycle_status = "active"
                if self._is_current_attempt(review, attempt):
                    review.current_position += 1
                    review.current_exercise_instance_id = None
                    review.status = "complete" if review.current_position >= len(review.selected_unit_ids) else "awaiting_question"
                response = {"original_assessment_id": original.id, "assessment_id": new.id, "status": "accepted", "review_status": review.status, "next_due_at": memory.next_due_at.isoformat() if memory else None}
            elif action in ("invalidate_attempt", "ambiguous_question", "factually_wrong_question"):
                attempt = self._attempt(session, attempt_id)
                if self._attempt_validity(session, attempt.id) == "invalid":
                    raise Conflict("attempt is already invalid")
                session.add(AttemptValidityEvent(attempt_id=attempt.id, validity_status="invalid", reason=action, actor=actor))
                if action != "invalidate_attempt":
                    session.get(ExerciseInstance, attempt.exercise_instance_id).validity_status = "invalid"
                review = session.get(ReviewSession, attempt.review_session_id)
                self._queue_retry(review, attempt)
                self._rebuild(session, review.learner_id, attempt.knowledge_unit_id)
                response = {"attempt_id": attempt.id, "validity_status": "invalid", "review_status": review.status}
            elif action == "correct_knowledge_unit":
                attempt = self._attempt(session, attempt_id)
                if not corrected_statement or exercise is None:
                    raise ValidationFailure("corrected_statement and exercise are required")
                unit = session.get(KnowledgeUnit, attempt.knowledge_unit_id)
                previous = session.scalar(select(KnowledgeUnitRevision).where(KnowledgeUnitRevision.knowledge_unit_id == unit.id, KnowledgeUnitRevision.revision == unit.current_revision))
                unit.current_revision += 1
                unit.version += 1
                unit.updated_at = now_utc()
                unit.lifecycle_status = "active"
                revision = KnowledgeUnitRevision(knowledge_unit_id=unit.id, revision=unit.current_revision, canonical_statement=corrected_statement.strip(), provenance_kind=previous.provenance_kind, uncertainty=previous.uncertainty, actor=actor)
                session.add(revision); session.flush()
                for link in session.scalars(select(KnowledgeUnitSource).where(KnowledgeUnitSource.knowledge_unit_revision_id == previous.id)):
                    session.add(KnowledgeUnitSource(knowledge_unit_revision_id=revision.id, source_revision_id=link.source_revision_id, locator=link.locator))
                session.add(ExerciseSpecification(knowledge_unit_revision_id=revision.id, exercise_type=exercise.exercise_type, required_elements=exercise.required_elements, acceptable_alternatives=exercise.acceptable_alternatives, common_errors=exercise.common_errors, difficulty_target=exercise.difficulty_target))
                index_document(session, "knowledge_unit", unit.id, unit.learner_id, "", revision.canonical_statement, revision.provenance_kind)
                review = session.get(ReviewSession, attempt.review_session_id)
                self._queue_retry(review, attempt)
                response = {"knowledge_unit_id": unit.id, "revision": unit.current_revision, "version": unit.version, "lifecycle_status": unit.lifecycle_status, "review_status": review.status}
            else:
                raise ValidationFailure("unsupported resolution action")
            aggregate_id = assessment_id or attempt_id or response.get("knowledge_unit_id")
            add_event(session, aggregate_type="learning_issue", aggregate_id=aggregate_id, event_type=f"learning_issue.{action}", actor=actor, correlation_id=correlation_id, payload={k: v for k, v in response.items() if k != "next_due_at"}, idempotency_key=idempotency_key, source_system="hermes")
            save_idempotent(session, "resolve_learning_issue", idempotency_key, request, response)
            return response

    def update_state(self, *, knowledge_unit_id: str | None = None, learner_id: str = "default",
                     policy_updates: dict | None = None, importance: float | None = None,
                     desired_retention: float | None = None, lifecycle_status: str | None = None,
                     expected_version: int | None = None, actor: str = "user",
                     correlation_id: str | None = None, idempotency_key: str) -> dict:
        if not idempotency_key.strip():
            raise ValidationFailure("idempotency_key must not be empty")
        correlation_id = correlation_id or str(uuid4())
        request = {"knowledge_unit_id": knowledge_unit_id, "learner_id": learner_id, "policy_updates": policy_updates, "importance": importance, "desired_retention": desired_retention, "lifecycle_status": lifecycle_status, "expected_version": expected_version}
        with self.db.transaction() as session:
            cached = get_idempotent(session, "update_learning_state", idempotency_key, request)
            if cached is not None:
                return cached
            if policy_updates is not None:
                allowed = {"daily_item_budget", "default_desired_retention", "default_importance", "low_confidence_threshold", "maintenance_probe_days", "capture_approval_default"}
                unknown = set(policy_updates) - allowed
                if unknown:
                    raise ValidationFailure(f"unknown policy fields: {sorted(unknown)}")
                policy = policy_for(session, learner_id)
                for key, value in policy_updates.items():
                    if key in ("default_desired_retention", "low_confidence_threshold") and not 0 < value < 1:
                        raise ValidationFailure(f"{key} must be between 0 and 1")
                    if key == "default_importance" and not 0 <= value <= 1:
                        raise ValidationFailure("default_importance must be between 0 and 1")
                    if key in ("daily_item_budget", "maintenance_probe_days") and (not isinstance(value, int) or value < 1):
                        raise ValidationFailure(f"{key} must be a positive integer")
                    setattr(policy, key, value)
                policy.updated_at = now_utc()
                response = {"learner_id": learner_id, "policy": {key: getattr(policy, key) for key in allowed}}
                add_event(session, aggregate_type="policy", aggregate_id=learner_id, event_type="policy.updated", actor=actor, correlation_id=correlation_id, payload={"fields": sorted(policy_updates)}, idempotency_key=idempotency_key, source_system="hermes")
                save_idempotent(session, "update_learning_state", idempotency_key, request, response)
                return response
            if knowledge_unit_id is None:
                raise ValidationFailure("knowledge_unit_id or policy_updates is required")
            unit = session.get(KnowledgeUnit, knowledge_unit_id)
            if unit is None:
                raise NotFound("knowledge unit not found")
            if expected_version is not None and unit.version != expected_version:
                raise Conflict("knowledge unit version conflict", {"expected_version": expected_version, "current_version": unit.version, "knowledge_unit_id": unit.id})
            if importance is not None:
                if not 0 <= importance <= 1: raise ValidationFailure("importance must be between 0 and 1")
                unit.importance = importance
            if desired_retention is not None:
                if not 0 < desired_retention < 1: raise ValidationFailure("desired_retention must be between 0 and 1")
                unit.desired_retention = desired_retention
            if lifecycle_status is not None:
                allowed = {"active", "suspended", "maintenance", "archived"}
                if lifecycle_status not in allowed: raise ValidationFailure(f"lifecycle_status must be one of {sorted(allowed)}")
                unit.lifecycle_status = lifecycle_status
            unit.version += 1; unit.updated_at = now_utc()
            memory = session.scalar(select(MemoryState).where(MemoryState.knowledge_unit_id == unit.id, MemoryState.learner_id == unit.learner_id))
            response = {"knowledge_unit_id": unit.id, "version": unit.version, "importance": unit.importance, "desired_retention": unit.desired_retention, "lifecycle_status": unit.lifecycle_status, "mastery_unchanged": True, "memory_state": memory.scheduler_state if memory else None}
            add_event(session, aggregate_type="knowledge_unit", aggregate_id=unit.id, event_type="learning_state.updated", actor=actor, correlation_id=correlation_id, payload={"importance": importance, "desired_retention": desired_retention, "lifecycle_status": lifecycle_status}, idempotency_key=idempotency_key, source_system="hermes")
            save_idempotent(session, "update_learning_state", idempotency_key, request, response)
            return response

    @staticmethod
    def _assessment(session, assessment_id):
        if not assessment_id: raise ValidationFailure("assessment_id is required")
        row = session.get(Assessment, assessment_id)
        if row is None: raise NotFound("assessment not found")
        return row

    @staticmethod
    def _attempt(session, attempt_id):
        if not attempt_id: raise ValidationFailure("attempt_id is required")
        row = session.get(Attempt, attempt_id)
        if row is None: raise NotFound("attempt not found")
        return row

    def _rebuild(self, session, learner_id, unit_id):
        return rebuild_memory_state(session, learner_id, unit_id, self.scheduler)

    @staticmethod
    def _is_current_attempt(review, attempt) -> bool:
        return (
            review.current_position < len(review.selected_unit_ids)
            and review.selected_unit_ids[review.current_position] == attempt.knowledge_unit_id
            and review.current_exercise_instance_id == attempt.exercise_instance_id
        )

    @classmethod
    def _queue_retry(cls, review, attempt) -> None:
        if cls._is_current_attempt(review, attempt):
            review.current_exercise_instance_id = None
            review.status = "awaiting_question"
            return
        if attempt.knowledge_unit_id not in review.selected_unit_ids[review.current_position:]:
            review.selected_unit_ids = [*review.selected_unit_ids, attempt.knowledge_unit_id]
        if review.status == "complete":
            review.status = "awaiting_question"

    @staticmethod
    def _assessment_status(session, assessment_id):
        latest = session.scalar(select(AssessmentStatusEvent).where(AssessmentStatusEvent.assessment_id == assessment_id).order_by(AssessmentStatusEvent.created_at.desc(), AssessmentStatusEvent.id.desc()).limit(1))
        return latest.status if latest else session.get(Assessment, assessment_id).status

    @staticmethod
    def _attempt_validity(session, attempt_id):
        latest = session.scalar(select(AttemptValidityEvent).where(AttemptValidityEvent.attempt_id == attempt_id).order_by(AttemptValidityEvent.created_at.desc(), AttemptValidityEvent.id.desc()).limit(1))
        return latest.validity_status if latest else session.get(Attempt, attempt_id).validity_status
