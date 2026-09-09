from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select

from noesis.application.common import add_event, as_utc, content_hash, get_idempotent, normalize_text, now_utc, policy_for, save_idempotent
from noesis.application.contracts import CaptureProposalInput, CommitCaptureInput, ConceptInput, EdgeInput, KnowledgeUnitInput, SourceInput
from noesis.domain.errors import Conflict, NotFound, ValidationFailure
from noesis.persistence.database import Database
from noesis.persistence.models import (
    CaptureProposal, CaptureProposalItem, Concept, ConceptEdge, ExerciseSpecification,
    KnowledgeUnit, KnowledgeUnitRevision, KnowledgeUnitSource, Source, SourceRevision,
)
from noesis.retrieval.indexing import index_document


class CaptureService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def propose(self, data: CaptureProposalInput, *, actor: str, idempotency_key: str, correlation_id: str | None = None) -> dict:
        if not idempotency_key.strip():
            raise ValidationFailure("idempotency_key must not be empty")
        correlation_id = correlation_id or str(uuid4())
        payload = data.model_dump(mode="json")
        duplicates: list[dict] = []
        with self.db.transaction() as session:
            cached = get_idempotent(session, "propose_capture", idempotency_key, payload)
            if cached is not None:
                return cached
            learner_policy = policy_for(session, data.learner_id)
            for source in data.sources:
                digest = content_hash(source.corrected_transcription or source.text or source.raw_transcription)
                existing = session.scalar(select(SourceRevision).join(Source, Source.id == SourceRevision.source_id).where(Source.learner_id == data.learner_id, SourceRevision.content_hash == digest))
                if existing:
                    duplicates.append({"item_type": "source", "client_id": source.client_id, "match_id": existing.source_id, "kind": "exact"})
                else:
                    identity = [Source.learner_id == data.learner_id, Source.source_type == source.source_type]
                    if source.external_ref:
                        identity.append(Source.external_ref == source.external_ref)
                    else:
                        identity.extend((Source.title == source.title, Source.author == source.author, Source.edition == source.edition))
                    logical_source = session.scalar(select(Source).where(*identity))
                    if logical_source:
                        duplicates.append({"item_type": "source", "client_id": source.client_id, "match_id": logical_source.id, "kind": "revision", "current_revision": logical_source.current_revision})
            for unit in data.knowledge_units:
                statement = normalize_text(unit.canonical_statement)
                existing = session.scalar(select(KnowledgeUnitRevision).join(KnowledgeUnit, KnowledgeUnit.id == KnowledgeUnitRevision.knowledge_unit_id).where(KnowledgeUnit.learner_id == data.learner_id, func.lower(KnowledgeUnitRevision.canonical_statement) == statement.lower()))
                if existing:
                    duplicates.append({"item_type": "knowledge_unit", "client_id": unit.client_id, "match_id": existing.knowledge_unit_id, "kind": "exact"})
                else:
                    tokens = [token for token in statement.split() if len(token) > 3][:8]
                    if tokens:
                        match = " OR ".join(f'"{token.replace(chr(34), "")}"' for token in tokens)
                        lexical = session.connection().exec_driver_sql(
                            "SELECT entity_id, bm25(learning_fts) AS score FROM learning_fts "
                            "WHERE learning_fts MATCH ? AND learner_id = ? AND entity_type = 'knowledge_unit' ORDER BY score LIMIT 3",
                            (match, data.learner_id),
                        ).mappings().all()
                        duplicates.extend({"item_type": "knowledge_unit", "client_id": unit.client_id, "match_id": row["entity_id"], "kind": "lexical", "score": row["score"]} for row in lexical)

            proposal = CaptureProposal(
                learner_id=data.learner_id, payload=payload, actor=actor,
                expires_at=now_utc() + timedelta(days=7),
                summary={"sources": len(data.sources), "concepts": len(data.concepts), "knowledge_units": len(data.knowledge_units), "edges": len(data.edges), "duplicates": duplicates, "approval_required": True, "capture_approval_default": learner_policy.capture_approval_default},
            )
            session.add(proposal)
            session.flush()
            proposal_items = []
            for item_type, items in (("source", data.sources), ("concept", data.concepts), ("knowledge_unit", data.knowledge_units)):
                for item in items:
                    row = CaptureProposalItem(proposal_id=proposal.id, client_id=item.client_id, item_type=item_type, payload=item.model_dump(mode="json"))
                    session.add(row); session.flush()
                    proposal_items.append({"item_id": row.id, "client_id": row.client_id, "item_type": row.item_type})
            for index, edge in enumerate(data.edges):
                row = CaptureProposalItem(proposal_id=proposal.id, client_id=f"edge:{index}", item_type="edge", payload=edge.model_dump(mode="json"))
                session.add(row); session.flush()
                proposal_items.append({"item_id": row.id, "client_id": row.client_id, "item_type": row.item_type})
            add_event(session, aggregate_type="capture_proposal", aggregate_id=proposal.id, event_type="capture.proposed", actor=actor, correlation_id=correlation_id, payload=proposal.summary, idempotency_key=idempotency_key, source_system="hermes")
            response = {"proposal_id": proposal.id, "status": proposal.status, "expires_at": proposal.expires_at.isoformat(), "items": proposal_items, **proposal.summary}
            save_idempotent(session, "propose_capture", idempotency_key, payload, response)
            return response

    def commit(self, data: CommitCaptureInput) -> dict:
        if not data.idempotency_key.strip():
            raise ValidationFailure("idempotency_key must not be empty")
        correlation_id = data.correlation_id or str(uuid4())
        request = data.model_dump(mode="json")
        with self.db.transaction() as session:
            cached = get_idempotent(session, "commit_capture", data.idempotency_key, request)
            if cached is not None:
                return cached
            proposal = session.get(CaptureProposal, data.proposal_id)
            if proposal is None:
                raise NotFound("capture proposal not found")
            if proposal.status != "pending":
                raise Conflict(f"capture proposal is {proposal.status}")
            if as_utc(proposal.expires_at) < now_utc():
                proposal.status = "expired"
                add_event(session, aggregate_type="capture_proposal", aggregate_id=proposal.id, event_type="capture.expired", actor="noesis", correlation_id=correlation_id, payload={}, idempotency_key=data.idempotency_key)
                session.commit()
                raise Conflict("capture proposal has expired")
            items = {item.id: item for item in session.scalars(select(CaptureProposalItem).where(CaptureProposalItem.proposal_id == proposal.id))}
            decisions = {decision.item_id: decision for decision in data.decisions}
            unknown = set(decisions) - set(items)
            if unknown:
                raise ValidationFailure(f"unknown proposal item ids: {sorted(unknown)}")

            policy = policy_for(session, proposal.learner_id)
            source_ids: dict[str, str] = {}
            source_revision_ids: dict[str, str] = {}
            concept_ids: dict[str, str] = {}
            created: dict[str, list[str]] = {"sources": [], "concepts": [], "knowledge_units": [], "edges": []}

            ordered = sorted(items.values(), key=lambda item: {"source": 0, "concept": 1, "knowledge_unit": 2, "edge": 3}[item.item_type])
            for item in ordered:
                decision = decisions.get(item.id)
                item.decision = decision.action if decision else "reject"
                if not decision or decision.action == "reject":
                    continue
                item_payload = dict(item.payload)
                item_payload.update(decision.edits)
                contract = {"source": SourceInput, "concept": ConceptInput, "knowledge_unit": KnowledgeUnitInput, "edge": EdgeInput}[item.item_type]
                item_payload = contract.model_validate(item_payload).model_dump(mode="json")
                if item.item_type == "source":
                    source, revision = self._create_source(session, proposal.learner_id, item_payload, data.actor)
                    source_ids[item.client_id], source_revision_ids[item.client_id] = source.id, revision.id
                    item.committed_entity_id = source.id
                    created["sources"].append(source.id)
                    add_event(session, aggregate_type="source", aggregate_id=source.id, event_type="source.revision_captured", actor=data.actor, correlation_id=correlation_id, payload={"revision": revision.revision, "content_hash": revision.content_hash}, idempotency_key=data.idempotency_key, source_system="hermes")
                elif item.item_type == "concept":
                    concept = Concept(learner_id=proposal.learner_id, title=item_payload["title"], description=item_payload.get("description", ""))
                    session.add(concept); session.flush()
                    concept_ids[item.client_id] = concept.id
                    item.committed_entity_id = concept.id
                    created["concepts"].append(concept.id)
                    add_event(session, aggregate_type="concept", aggregate_id=concept.id, event_type="concept.created", actor=data.actor, correlation_id=correlation_id, payload={"lifecycle_status": concept.lifecycle_status}, idempotency_key=data.idempotency_key, source_system="hermes")
                    index_document(session, "concept", concept.id, proposal.learner_id, concept.title, concept.description, "concept")
                elif item.item_type == "knowledge_unit":
                    concept_id = concept_ids.get(item_payload["concept_client_id"])
                    if not concept_id:
                        raise ValidationFailure("approved knowledge unit requires its proposed concept to be approved")
                    unit = KnowledgeUnit(
                        learner_id=proposal.learner_id, concept_id=concept_id, kind=item_payload["kind"],
                        importance=item_payload.get("importance") if item_payload.get("importance") is not None else policy.default_importance,
                        desired_retention=item_payload.get("desired_retention") if item_payload.get("desired_retention") is not None else policy.default_desired_retention,
                        creation_actor=data.actor,
                    )
                    session.add(unit); session.flush()
                    revision = KnowledgeUnitRevision(
                        knowledge_unit_id=unit.id, revision=1, canonical_statement=normalize_text(item_payload["canonical_statement"]),
                        provenance_kind=item_payload["provenance_kind"], uncertainty=item_payload.get("uncertainty"), actor=data.actor,
                    )
                    session.add(revision); session.flush()
                    source_client_id = item_payload.get("source_client_id")
                    if source_client_id:
                        if source_client_id not in source_revision_ids:
                            raise ValidationFailure("approved knowledge unit requires its proposed source to be approved")
                        session.add(KnowledgeUnitSource(knowledge_unit_revision_id=revision.id, source_revision_id=source_revision_ids[source_client_id], locator=item_payload.get("locator", {})))
                    exercise = item_payload["exercise"]
                    session.add(ExerciseSpecification(
                        knowledge_unit_revision_id=revision.id, exercise_type=exercise["exercise_type"],
                        required_elements=exercise["required_elements"], acceptable_alternatives=exercise.get("acceptable_alternatives", []),
                        common_errors=exercise.get("common_errors", []), difficulty_target=exercise.get("difficulty_target", 0.5),
                    ))
                    item.committed_entity_id = unit.id
                    created["knowledge_units"].append(unit.id)
                    add_event(session, aggregate_type="knowledge_unit", aggregate_id=unit.id, event_type="knowledge_unit.created", actor=data.actor, correlation_id=correlation_id, payload={"revision": 1, "provenance_kind": revision.provenance_kind}, idempotency_key=data.idempotency_key, source_system="hermes")
                    index_document(session, "knowledge_unit", unit.id, proposal.learner_id, "", revision.canonical_statement, revision.provenance_kind)
                else:
                    from_id = concept_ids.get(item_payload["from_concept_client_id"])
                    to_id = concept_ids.get(item_payload["to_concept_client_id"])
                    if not from_id or not to_id:
                        raise ValidationFailure("approved edge requires both proposed concepts to be approved")
                    edge = ConceptEdge(from_concept_id=from_id, to_concept_id=to_id, edge_type=item_payload["edge_type"], provenance_kind=item_payload["provenance_kind"])
                    session.add(edge); session.flush()
                    item.committed_entity_id = edge.id
                    created["edges"].append(edge.id)
                    add_event(session, aggregate_type="concept_edge", aggregate_id=edge.id, event_type="concept_edge.created", actor=data.actor, correlation_id=correlation_id, payload={"edge_type": edge.edge_type, "provenance_kind": edge.provenance_kind}, idempotency_key=data.idempotency_key, source_system="hermes")

            proposal.status = "committed"
            proposal.committed_at = now_utc()
            add_event(session, aggregate_type="capture_proposal", aggregate_id=proposal.id, event_type="capture.committed", actor=data.actor, correlation_id=correlation_id, payload={k: len(v) for k, v in created.items()}, idempotency_key=data.idempotency_key, source_system="hermes")
            response = {"proposal_id": proposal.id, "status": "committed", "created": created}
            save_idempotent(session, "commit_capture", data.idempotency_key, request, response)
            return response

    @staticmethod
    def _create_source(session, learner_id: str, payload: dict, actor: str):
        text = payload.get("corrected_transcription") or payload.get("text") or payload.get("raw_transcription") or ""
        identity = [Source.learner_id == learner_id, Source.source_type == payload["source_type"]]
        if payload.get("external_ref"):
            identity.append(Source.external_ref == payload["external_ref"])
        else:
            identity.extend((Source.title == payload["title"], Source.author == payload.get("author"), Source.edition == payload.get("edition")))
        source = session.scalar(select(Source).where(*identity))
        digest = content_hash(text)
        if source is not None:
            existing_revision = session.scalar(select(SourceRevision).where(SourceRevision.source_id == source.id, SourceRevision.content_hash == digest))
            if existing_revision is not None:
                return source, existing_revision
            source.current_revision += 1
            source.updated_at = now_utc()
        else:
            source = Source(
                learner_id=learner_id, source_type=payload["source_type"], title=payload["title"], author=payload.get("author"),
                external_ref=payload.get("external_ref"), attachment_ref=payload.get("attachment_ref"), edition=payload.get("edition"),
                parent_source_id=payload.get("parent_source_id"),
            )
            session.add(source); session.flush()
        revision = SourceRevision(
            source_id=source.id, revision=source.current_revision, content_hash=digest, normalized_text=normalize_text(payload.get("text")),
            raw_transcription=payload.get("raw_transcription"), corrected_transcription=payload.get("corrected_transcription"),
            transcription_confidence=payload.get("transcription_confidence"), locator=payload.get("locator", {}),
            source_metadata=payload.get("metadata", {}), capture_actor=actor,
        )
        session.add(revision); session.flush()
        if source.current_revision > 1:
            affected_units = session.scalars(
                select(KnowledgeUnit)
                .join(KnowledgeUnitRevision, KnowledgeUnitRevision.knowledge_unit_id == KnowledgeUnit.id)
                .join(KnowledgeUnitSource, KnowledgeUnitSource.knowledge_unit_revision_id == KnowledgeUnitRevision.id)
                .join(SourceRevision, SourceRevision.id == KnowledgeUnitSource.source_revision_id)
                .where(SourceRevision.source_id == source.id, KnowledgeUnit.lifecycle_status == "maintenance")
            )
            for affected in affected_units:
                affected.lifecycle_status = "active"
        index_document(session, "source", source.id, learner_id, source.title, normalize_text(text), "source")
        return source, revision
