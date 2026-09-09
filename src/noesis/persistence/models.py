from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class CaptureProposal(Base):
    __tablename__ = "capture_proposals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    learner_id: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    actor: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)


class CaptureProposalItem(Base):
    __tablename__ = "capture_proposal_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("capture_proposals.id", ondelete="CASCADE"), index=True)
    client_id: Mapped[str] = mapped_column(String(128))
    item_type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    decision: Mapped[str | None] = mapped_column(String(32))
    committed_entity_id: Mapped[str | None] = mapped_column(String(36))
    __table_args__ = (UniqueConstraint("proposal_id", "item_type", "client_id"),)


class Source(Base):
    __tablename__ = "sources"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    learner_id: Mapped[str] = mapped_column(String(128), index=True)
    source_type: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(Text)
    external_ref: Mapped[str | None] = mapped_column(Text)
    attachment_ref: Mapped[str | None] = mapped_column(Text)
    edition: Mapped[str | None] = mapped_column(Text)
    parent_source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id"))
    current_revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (Index("ix_source_identity", "learner_id", "source_type", "title", "author"),)


class SourceRevision(Base):
    __tablename__ = "source_revisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    normalized_text: Mapped[str | None] = mapped_column(Text)
    raw_transcription: Mapped[str | None] = mapped_column(Text)
    corrected_transcription: Mapped[str | None] = mapped_column(Text)
    transcription_confidence: Mapped[float | None] = mapped_column(Float)
    locator: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    capture_actor: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("source_id", "revision"), UniqueConstraint("source_id", "content_hash"))


class Concept(Base):
    __tablename__ = "concepts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    learner_id: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    lifecycle_status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeUnit(Base):
    __tablename__ = "knowledge_units"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    learner_id: Mapped[str] = mapped_column(String(128), index=True)
    concept_id: Mapped[str] = mapped_column(ForeignKey("concepts.id"), index=True)
    kind: Mapped[str] = mapped_column(String(64))
    current_revision: Mapped[int] = mapped_column(Integer, default=1)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    desired_retention: Mapped[float] = mapped_column(Float, default=0.9)
    lifecycle_status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    validity_status: Mapped[str] = mapped_column(String(32), default="valid")
    creation_actor: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    version: Mapped[int] = mapped_column(Integer, default=1)


class KnowledgeUnitRevision(Base):
    __tablename__ = "knowledge_unit_revisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    knowledge_unit_id: Mapped[str] = mapped_column(ForeignKey("knowledge_units.id", ondelete="CASCADE"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    canonical_statement: Mapped[str] = mapped_column(Text)
    provenance_kind: Mapped[str] = mapped_column(String(32))
    uncertainty: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("knowledge_unit_id", "revision"),)


class KnowledgeUnitSource(Base):
    __tablename__ = "knowledge_unit_sources"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    knowledge_unit_revision_id: Mapped[str] = mapped_column(ForeignKey("knowledge_unit_revisions.id", ondelete="CASCADE"), index=True)
    source_revision_id: Mapped[str] = mapped_column(ForeignKey("source_revisions.id"), index=True)
    locator: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ConceptEdge(Base):
    __tablename__ = "concept_edges"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    from_concept_id: Mapped[str] = mapped_column(ForeignKey("concepts.id"), index=True)
    to_concept_id: Mapped[str] = mapped_column(ForeignKey("concepts.id"), index=True)
    edge_type: Mapped[str] = mapped_column(String(32))
    provenance_kind: Mapped[str] = mapped_column(String(32))
    approval_status: Mapped[str] = mapped_column(String(32), default="approved")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("from_concept_id", "to_concept_id", "edge_type"),)


class ExerciseSpecification(Base):
    __tablename__ = "exercise_specifications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    knowledge_unit_revision_id: Mapped[str] = mapped_column(ForeignKey("knowledge_unit_revisions.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    exercise_type: Mapped[str] = mapped_column(String(32))
    required_elements: Mapped[list[str]] = mapped_column(JSON)
    acceptable_alternatives: Mapped[list[str]] = mapped_column(JSON, default=list)
    common_errors: Mapped[list[str]] = mapped_column(JSON, default=list)
    difficulty_target: Mapped[float] = mapped_column(Float, default=0.5)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExerciseInstance(Base):
    __tablename__ = "exercise_instances"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    specification_id: Mapped[str] = mapped_column(ForeignKey("exercise_specifications.id"), index=True)
    question_text: Mapped[str] = mapped_column(Text)
    generation_context_ref: Mapped[str | None] = mapped_column(Text)
    model_id: Mapped[str | None] = mapped_column(String(256))
    prompt_version: Mapped[str | None] = mapped_column(String(128))
    validity_status: Mapped[str] = mapped_column(String(32), default="valid")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReviewSession(Base):
    __tablename__ = "review_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    learner_id: Mapped[str] = mapped_column(String(128), index=True)
    selected_unit_ids: Mapped[list[str]] = mapped_column(JSON)
    current_position: Mapped[int] = mapped_column(Integer, default=0)
    current_exercise_instance_id: Mapped[str | None] = mapped_column(ForeignKey("exercise_instances.id"))
    status: Mapped[str] = mapped_column(String(32), default="created", index=True)
    origin_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    version: Mapped[int] = mapped_column(Integer, default=1)


class Attempt(Base):
    __tablename__ = "attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    review_session_id: Mapped[str] = mapped_column(ForeignKey("review_sessions.id"), index=True)
    exercise_instance_id: Mapped[str] = mapped_column(ForeignKey("exercise_instances.id"), index=True)
    knowledge_unit_id: Mapped[str] = mapped_column(ForeignKey("knowledge_units.id"), index=True)
    exact_response: Mapped[str] = mapped_column(Text)
    hints_used: Mapped[list[str]] = mapped_column(JSON, default=list)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    user_confidence: Mapped[float | None] = mapped_column(Float)
    validity_status: Mapped[str] = mapped_column(String(32), default="valid")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Assessment(Base):
    __tablename__ = "assessments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    attempt_id: Mapped[str] = mapped_column(ForeignKey("attempts.id"), index=True)
    recall_outcome: Mapped[str] = mapped_column(String(32))
    evidence: Mapped[list[str]] = mapped_column(JSON, default=list)
    missing_elements: Mapped[list[str]] = mapped_column(JSON, default=list)
    possible_misconception: Mapped[str | None] = mapped_column(Text)
    assessor_confidence: Mapped[float] = mapped_column(Float)
    user_confidence: Mapped[float | None] = mapped_column(Float)
    model_id: Mapped[str] = mapped_column(String(256))
    rubric_version: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), index=True)
    supersedes_assessment_id: Mapped[str | None] = mapped_column(ForeignKey("assessments.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class AssessmentStatusEvent(Base):
    __tablename__ = "assessment_status_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    assessment_id: Mapped[str] = mapped_column(ForeignKey("assessments.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class AttemptValidityEvent(Base):
    __tablename__ = "attempt_validity_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    attempt_id: Mapped[str] = mapped_column(ForeignKey("attempts.id", ondelete="CASCADE"), index=True)
    validity_status: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class MemoryState(Base):
    __tablename__ = "memory_states"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    learner_id: Mapped[str] = mapped_column(String(128))
    knowledge_unit_id: Mapped[str] = mapped_column(ForeignKey("knowledge_units.id", ondelete="CASCADE"))
    scheduler_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    scheduler_version: Mapped[str] = mapped_column(String(64))
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (UniqueConstraint("learner_id", "knowledge_unit_id"),)


class SchedulerTransition(Base):
    __tablename__ = "scheduler_transitions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    learner_id: Mapped[str] = mapped_column(String(128), index=True)
    knowledge_unit_id: Mapped[str] = mapped_column(ForeignKey("knowledge_units.id"), index=True)
    assessment_id: Mapped[str] = mapped_column(ForeignKey("assessments.id"), unique=True)
    grade: Mapped[int] = mapped_column(Integer)
    desired_retention: Mapped[float] = mapped_column(Float)
    scheduler_version: Mapped[str] = mapped_column(String(64))
    input_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_state: Mapped[dict[str, Any]] = mapped_column(JSON)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    next_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    explanation: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LearnerPolicy(Base):
    __tablename__ = "learner_policies"
    learner_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    daily_item_budget: Mapped[int] = mapped_column(Integer, default=10)
    default_desired_retention: Mapped[float] = mapped_column(Float, default=0.9)
    default_importance: Mapped[float] = mapped_column(Float, default=0.5)
    low_confidence_threshold: Mapped[float] = mapped_column(Float, default=0.7)
    maintenance_probe_days: Mapped[int] = mapped_column(Integer, default=90)
    capture_approval_default: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    aggregate_type: Mapped[str] = mapped_column(String(64), index=True)
    aggregate_id: Mapped[str] = mapped_column(String(36), index=True)
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    actor: Mapped[str] = mapped_column(String(128))
    source_system: Mapped[str] = mapped_column(String(128))
    correlation_id: Mapped[str] = mapped_column(String(128), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(256), index=True)
    model_id: Mapped[str | None] = mapped_column(String(256))
    prompt_version: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    operation: Mapped[str] = mapped_column(String(128))
    key: Mapped[str] = mapped_column(String(256))
    request_hash: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("operation", "key"),)


class RebuildFailure(Base):
    __tablename__ = "rebuild_failures"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    knowledge_unit_id: Mapped[str] = mapped_column(ForeignKey("knowledge_units.id"), index=True)
    error: Mapped[str] = mapped_column(Text)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
