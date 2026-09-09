from __future__ import annotations

import re
from datetime import timedelta

from sqlalchemy import func, select

from noesis.application.common import now_utc
from noesis.persistence.database import Database
from noesis.persistence.models import (
    Assessment, AssessmentStatusEvent, Attempt, Concept, ConceptEdge, KnowledgeUnit, KnowledgeUnitRevision,
    KnowledgeUnitSource, MemoryState, ReviewSession, Source, SourceRevision,
)


def _fts_query(text: str) -> str:
    tokens = re.findall(r"[\w]+", text, flags=re.UNICODE)[:20]
    return " OR ".join(f'"{token}"' for token in tokens)


class QueryService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def recall(self, *, query: str, learner_id: str = "default", limit: int = 10, include_suspended: bool = False) -> dict:
        match = _fts_query(query)
        if not match:
            return {"query": query, "results": []}
        with self.db.read() as session:
            rows = session.connection().exec_driver_sql(
                "SELECT entity_type, entity_id, title, body, provenance, bm25(learning_fts) AS score "
                "FROM learning_fts WHERE learning_fts MATCH ? AND learner_id = ? ORDER BY score LIMIT ?",
                (match, learner_id, max(1, min(limit, 50))),
            ).mappings().all()
            results = []
            for row in rows:
                if row["entity_type"] == "knowledge_unit":
                    unit = session.get(KnowledgeUnit, row["entity_id"])
                    if not unit or unit.validity_status != "valid" or (not include_suspended and unit.lifecycle_status in ("suspended", "archived")):
                        continue
                    revision = session.scalar(select(KnowledgeUnitRevision).where(KnowledgeUnitRevision.knowledge_unit_id == unit.id, KnowledgeUnitRevision.revision == unit.current_revision))
                    links = session.execute(
                        select(Source, SourceRevision, KnowledgeUnitSource)
                        .join(SourceRevision, SourceRevision.source_id == Source.id)
                        .join(KnowledgeUnitSource, KnowledgeUnitSource.source_revision_id == SourceRevision.id)
                        .where(KnowledgeUnitSource.knowledge_unit_revision_id == revision.id)
                    ).all()
                    results.append({
                        "entity_type": "knowledge_unit", "knowledge_unit_id": unit.id,
                        "statement": revision.canonical_statement, "provenance_kind": revision.provenance_kind,
                        "uncertainty": revision.uncertainty, "lifecycle_status": unit.lifecycle_status,
                        "relationships": self._relationships(session, unit.concept_id),
                        "sources": [{"source_id": source.id, "title": source.title, "author": source.author, "revision": source_revision.revision, "content_hash": source_revision.content_hash, "locator": link.locator} for source, source_revision, link in links],
                        "lexical_score": row["score"],
                    })
                elif row["entity_type"] == "concept":
                    concept = session.get(Concept, row["entity_id"])
                    if concept and (include_suspended or concept.lifecycle_status not in ("suspended", "archived")):
                        results.append({"entity_type": "concept", "concept_id": concept.id, "title": concept.title, "description": concept.description, "relationships": self._relationships(session, concept.id), "lexical_score": row["score"]})
                elif row["entity_type"] == "source":
                    source = session.get(Source, row["entity_id"])
                    if source:
                        revision = session.scalar(select(SourceRevision).where(SourceRevision.source_id == source.id, SourceRevision.revision == source.current_revision))
                        results.append({"entity_type": "source", "source_id": source.id, "title": source.title, "author": source.author, "revision": revision.revision, "content_hash": revision.content_hash, "locator": revision.locator, "lexical_score": row["score"]})
            return {"query": query, "results": results[:limit], "synthesis_required": True}

    @staticmethod
    def _relationships(session, concept_id: str) -> list[dict]:
        edges = session.scalars(select(ConceptEdge).where((ConceptEdge.from_concept_id == concept_id) | (ConceptEdge.to_concept_id == concept_id), ConceptEdge.approval_status == "approved"))
        relationships = []
        for edge in edges:
            outgoing = edge.from_concept_id == concept_id
            other_id = edge.to_concept_id if outgoing else edge.from_concept_id
            other = session.get(Concept, other_id)
            relationships.append({"edge_id": edge.id, "edge_type": edge.edge_type, "direction": "outgoing" if outgoing else "incoming", "other_concept_id": other_id, "other_concept_title": other.title if other else None, "provenance_kind": edge.provenance_kind})
        return relationships

    def progress(self, *, learner_id: str = "default") -> dict:
        now = now_utc()
        with self.db.read() as session:
            lifecycle = dict(session.execute(select(KnowledgeUnit.lifecycle_status, func.count()).where(KnowledgeUnit.learner_id == learner_id).group_by(KnowledgeUnit.lifecycle_status)).all())
            due = session.scalar(select(func.count(MemoryState.id)).join(KnowledgeUnit, KnowledgeUnit.id == MemoryState.knowledge_unit_id).where(MemoryState.learner_id == learner_id, MemoryState.next_due_at <= now, KnowledgeUnit.lifecycle_status.in_(("active", "maintenance")))) or 0
            new_units = session.scalar(select(func.count(KnowledgeUnit.id)).outerjoin(MemoryState, MemoryState.knowledge_unit_id == KnowledgeUnit.id).where(KnowledgeUnit.learner_id == learner_id, KnowledgeUnit.lifecycle_status == "active", MemoryState.id.is_(None))) or 0
            learner_assessments = list(session.scalars(
                select(Assessment)
                .join(Attempt, Attempt.id == Assessment.attempt_id)
                .join(KnowledgeUnit, KnowledgeUnit.id == Attempt.knowledge_unit_id)
                .where(KnowledgeUnit.learner_id == learner_id)
            ))
            effective_status = {
                assessment.id: (
                    session.scalar(select(AssessmentStatusEvent.status).where(AssessmentStatusEvent.assessment_id == assessment.id).order_by(AssessmentStatusEvent.created_at.desc(), AssessmentStatusEvent.id.desc()).limit(1))
                    or assessment.status
                ) for assessment in learner_assessments
            }
            pending_assessments = sum(status in ("proposed", "disputed") for status in effective_status.values())
            open_sessions = session.scalar(select(func.count(ReviewSession.id)).where(ReviewSession.learner_id == learner_id, ReviewSession.status.in_(("created", "awaiting_question", "awaiting_answer", "awaiting_resolution")))) or 0
            recent = session.execute(
                select(Assessment, Attempt).join(Attempt, Attempt.id == Assessment.attempt_id)
                .join(KnowledgeUnit, KnowledgeUnit.id == Attempt.knowledge_unit_id)
                .where(KnowledgeUnit.learner_id == learner_id, Assessment.created_at >= now - timedelta(days=7))
                .order_by(Assessment.created_at.desc()).limit(20)
            ).all()
            fragile = session.execute(
                select(KnowledgeUnit.id, KnowledgeUnitRevision.canonical_statement, MemoryState.consecutive_failures)
                .join(MemoryState, MemoryState.knowledge_unit_id == KnowledgeUnit.id)
                .join(KnowledgeUnitRevision, (KnowledgeUnitRevision.knowledge_unit_id == KnowledgeUnit.id) & (KnowledgeUnitRevision.revision == KnowledgeUnit.current_revision))
                .where(KnowledgeUnit.learner_id == learner_id, MemoryState.consecutive_failures > 0)
                .order_by(MemoryState.consecutive_failures.desc()).limit(10)
            ).all()
            maintenance = session.execute(
                select(KnowledgeUnit.id, KnowledgeUnitRevision.canonical_statement, MemoryState.next_due_at)
                .join(KnowledgeUnitRevision, (KnowledgeUnitRevision.knowledge_unit_id == KnowledgeUnit.id) & (KnowledgeUnitRevision.revision == KnowledgeUnit.current_revision))
                .outerjoin(MemoryState, (MemoryState.knowledge_unit_id == KnowledgeUnit.id) & (MemoryState.learner_id == learner_id))
                .where(KnowledgeUnit.learner_id == learner_id, KnowledgeUnit.lifecycle_status == "maintenance")
                .order_by(MemoryState.next_due_at.asc().nullsfirst()).limit(20)
            ).all()
            return {
                "learner_id": learner_id,
                "due_load": due + new_units,
                "due_reviewed_units": due,
                "new_units": new_units,
                "lifecycle_counts": lifecycle,
                "pending_assessments": pending_assessments,
                "open_review_sessions": open_sessions,
                "fragile_units": [{"knowledge_unit_id": row[0], "statement": row[1], "consecutive_failures": row[2]} for row in fragile],
                "maintenance_items": [{"knowledge_unit_id": row[0], "statement": row[1], "next_due_at": row[2].isoformat() if row[2] else None} for row in maintenance],
                "recent_assessments": [{"assessment_id": assessment.id, "attempt_id": attempt.id, "outcome": assessment.recall_outcome, "status": effective_status[assessment.id], "created_at": assessment.created_at.isoformat()} for assessment, attempt in recent],
                "explanation": {"due_load": "Eligible new units plus active or maintenance memory states whose due time has passed.", "fragile_units": "Units with one or more consecutive accepted failures."},
            }
