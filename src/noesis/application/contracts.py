from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceInput(Contract):
    client_id: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    title: str = Field(min_length=1)
    author: str | None = None
    external_ref: str | None = None
    attachment_ref: str | None = None
    edition: str | None = None
    text: str | None = None
    raw_transcription: str | None = None
    corrected_transcription: str | None = None
    transcription_confidence: float | None = Field(None, ge=0, le=1)
    locator: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    parent_source_id: str | None = None

    @model_validator(mode="after")
    def has_hashable_content(self):
        if not (self.text or self.raw_transcription or self.corrected_transcription):
            raise ValueError("a source requires text or transcription for content hashing")
        return self


class ConceptInput(Contract):
    client_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = ""


class KnowledgeUnitInput(Contract):
    client_id: str = Field(min_length=1)
    concept_client_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    canonical_statement: str = Field(min_length=1)
    source_client_id: str | None = None
    locator: dict[str, Any] = Field(default_factory=dict)
    provenance_kind: Literal["source_claim", "user_interpretation", "hermes_synthesis"]
    uncertainty: str | None = None
    importance: float | None = Field(None, ge=0, le=1)
    desired_retention: float | None = Field(None, gt=0, lt=1)
    exercise: "ExerciseSpecInput"


class ExerciseSpecInput(Contract):
    exercise_type: Literal["free_recall", "explain_own_words", "compare_contrast", "application_scenario"]
    required_elements: list[str] = Field(min_length=1)
    acceptable_alternatives: list[str] = Field(default_factory=list)
    common_errors: list[str] = Field(default_factory=list)
    difficulty_target: float = Field(default=0.5, ge=0, le=1)


class EdgeInput(Contract):
    from_concept_client_id: str
    to_concept_client_id: str
    edge_type: Literal["prerequisite_of", "contrasts_with", "related_to"]
    provenance_kind: Literal["source_asserted", "hermes_synthesized"]


class CaptureProposalInput(Contract):
    learner_id: str = "default"
    sources: list[SourceInput]
    concepts: list[ConceptInput]
    knowledge_units: list[KnowledgeUnitInput]
    edges: list[EdgeInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def references_exist(self):
        source_ids = {source.client_id for source in self.sources}
        concept_ids = {concept.client_id for concept in self.concepts}
        if len(source_ids) != len(self.sources) or len(concept_ids) != len(self.concepts):
            raise ValueError("client_id values must be unique within their item type")
        for unit in self.knowledge_units:
            if unit.concept_client_id not in concept_ids:
                raise ValueError(f"unknown concept_client_id: {unit.concept_client_id}")
            if unit.source_client_id and unit.source_client_id not in source_ids:
                raise ValueError(f"unknown source_client_id: {unit.source_client_id}")
        for edge in self.edges:
            if edge.from_concept_client_id not in concept_ids or edge.to_concept_client_id not in concept_ids:
                raise ValueError("edge references an unknown concept_client_id")
            if edge.from_concept_client_id == edge.to_concept_client_id:
                raise ValueError("self-referential concept edges are not allowed")
        return self


class CaptureDecision(Contract):
    item_id: str
    action: Literal["approve", "reject"]
    edits: dict[str, Any] = Field(default_factory=dict)


class CommitCaptureInput(Contract):
    proposal_id: str
    decisions: list[CaptureDecision]
    actor: str = "user"
    correlation_id: str | None = None
    idempotency_key: str


class AssessmentInput(Contract):
    recall_outcome: Literal["failed", "difficult", "successful", "effortless", "ungradable"]
    evidence: list[str] = Field(default_factory=list)
    missing_elements: list[str] = Field(default_factory=list)
    possible_misconception: str | None = None
    assessor_confidence: float = Field(ge=0, le=1)
    user_confidence: float | None = Field(None, ge=0, le=1)
    model_id: str
    rubric_version: str
    user_disagrees: bool = False
