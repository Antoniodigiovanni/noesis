from copy import deepcopy

from sqlalchemy import func, select

from noesis.application.contracts import AssessmentInput, CaptureProposalInput, CommitCaptureInput, ExerciseSpecInput
from noesis.persistence.models import Assessment, AssessmentStatusEvent, Attempt, AttemptValidityEvent, Event, KnowledgeUnit, KnowledgeUnitRevision, KnowledgeUnitSource, MemoryState, Source, SourceRevision


def meditations_payload(text=None):
    return {
        "learner_id": "default",
        "sources": [{
            "client_id": "meditations-notes", "source_type": "notes", "title": "Notes on Meditations",
            "author": "Antonio", "external_ref": "notes://meditations", "text": text or "I cannot control other people's choices, but I can control how deliberately I respond.",
            "metadata": {"book": "Meditations", "book_author": "Marcus Aurelius"},
        }],
        "concepts": [
            {"client_id": "control", "title": "Control and response", "description": "Distinguishing choices from responses"},
            {"client_id": "impermanence", "title": "Impermanence", "description": "Using impermanence to reduce status weight"},
        ],
        "knowledge_units": [
            {"client_id": "ku-control", "concept_client_id": "control", "kind": "distinction", "canonical_statement": "Other people's choices are not controllable, while one's deliberate response is.", "source_client_id": "meditations-notes", "provenance_kind": "user_interpretation", "exercise": {"exercise_type": "explain_own_words", "required_elements": ["other people's choices", "deliberate response"]}},
            {"client_id": "ku-emotion", "concept_client_id": "impermanence", "kind": "question", "canonical_statement": "Impermanence may reduce the emotional weight of status and conflict.", "source_client_id": "meditations-notes", "provenance_kind": "user_interpretation", "uncertainty": "Unclear whether this means suppressing emotion or changing judgment.", "exercise": {"exercise_type": "compare_contrast", "required_elements": ["emotion suppression", "changed judgment"]}},
        ],
        "edges": [{"from_concept_client_id": "control", "to_concept_client_id": "impermanence", "edge_type": "related_to", "provenance_kind": "hermes_synthesized"}],
    }


def capture(core, payload=None):
    proposal = core.capture.propose(CaptureProposalInput.model_validate(payload or meditations_payload()), actor="hermes", idempotency_key=f"proposal-{(payload or {}).get('learner_id', 'default')}-{(payload or meditations_payload())['sources'][0]['text']}")
    decisions = [{"item_id": item["item_id"], "action": "approve"} for item in proposal["items"]]
    result = core.capture.commit(CommitCaptureInput.model_validate({"proposal_id": proposal["proposal_id"], "decisions": decisions, "idempotency_key": "capture-1"}))
    return proposal, result


def test_capture_requires_commit_and_is_idempotent(core):
    proposal = core.capture.propose(CaptureProposalInput.model_validate(meditations_payload()), actor="hermes", idempotency_key="proposal-1")
    with core.db.read() as session:
        assert session.scalar(select(func.count(KnowledgeUnit.id))) == 0
    decisions = [{"item_id": item["item_id"], "action": "approve"} for item in proposal["items"]]
    request = CommitCaptureInput.model_validate({"proposal_id": proposal["proposal_id"], "decisions": decisions, "idempotency_key": "capture-1"})
    first = core.capture.commit(request)
    assert core.capture.commit(request) == first
    with core.db.read() as session:
        assert session.scalar(select(func.count(KnowledgeUnit.id))) == 2
        assert session.scalar(select(func.count(Event.id))) >= 2


def test_source_revision_does_not_overwrite(core):
    capture(core)
    changed = meditations_payload("Revised notes about deliberate responses and what is outside control.")
    proposal = core.capture.propose(CaptureProposalInput.model_validate(changed), actor="hermes", idempotency_key="proposal-2")
    assert any(match["kind"] == "revision" for match in proposal["duplicates"])
    source_item = next(item for item in proposal["items"] if item["item_type"] == "source")
    concept_items = [item for item in proposal["items"] if item["item_type"] == "concept"]
    decisions = [{"item_id": source_item["item_id"], "action": "approve"}] + [{"item_id": item["item_id"], "action": "reject"} for item in proposal["items"] if item != source_item]
    core.capture.commit(CommitCaptureInput.model_validate({"proposal_id": proposal["proposal_id"], "decisions": decisions, "idempotency_key": "capture-2"}))
    with core.db.read() as session:
        source = session.scalar(select(Source))
        revisions = list(session.scalars(select(SourceRevision).where(SourceRevision.source_id == source.id).order_by(SourceRevision.revision)))
        assert source.current_revision == 2
        assert len(revisions) == 2
        assert revisions[0].content_hash != revisions[1].content_hash


def test_review_gating_dispute_rebuild_and_importance_separation(core):
    _, committed = capture(core)
    unit_id = committed["created"]["knowledge_units"][0]
    review = core.reviews.start(learner_id="default", idempotency_key="review-start")
    review = core.reviews.start(learner_id="default", session_id=review["review_session_id"], question_text="What can you control?", model_id="test:model", prompt_version="q-v1", idempotency_key="question-1")
    low = AssessmentInput(recall_outcome="difficult", evidence=["response mentioned control"], missing_elements=["deliberate response"], assessor_confidence=0.5, model_id="test:model", rubric_version="rubric-v1")
    held = core.reviews.submit(review_session_id=review["review_session_id"], exact_response="I cannot control others.", assessment=low, idempotency_key="attempt-1")
    assert held["review_status"] == "awaiting_resolution"
    assert held["scheduler_update"] is None
    resolved = core.learning.resolve(action="accept_self_grade", assessment_id=held["assessment_id"], self_grade="difficult", idempotency_key="resolve-1")
    assert resolved["status"] == "accepted"
    with core.db.read() as session:
        memory_before = deepcopy(session.scalar(select(MemoryState).where(MemoryState.knowledge_unit_id == unit_id)).scheduler_state)
    updated = core.learning.update_state(knowledge_unit_id=unit_id, importance=1.0, desired_retention=0.95, idempotency_key="importance-1")
    assert updated["mastery_unchanged"] is True
    with core.db.read() as session:
        assert session.scalar(select(MemoryState).where(MemoryState.knowledge_unit_id == unit_id)).scheduler_state == memory_before
        attempt = session.scalar(select(Attempt).where(Attempt.knowledge_unit_id == unit_id))
        original = session.get(Assessment, held["assessment_id"])
        assert original.status == "proposed"
        latest_status = session.scalar(select(AssessmentStatusEvent.status).where(AssessmentStatusEvent.assessment_id == original.id).order_by(AssessmentStatusEvent.created_at.desc(), AssessmentStatusEvent.id.desc()))
        assert latest_status == "superseded"
    invalid = core.learning.resolve(action="ambiguous_question", attempt_id=attempt.id, idempotency_key="invalid-1")
    assert invalid["validity_status"] == "invalid"
    with core.db.read() as session:
        assert session.scalar(select(MemoryState).where(MemoryState.knowledge_unit_id == unit_id)) is None
        persisted_attempt = session.get(Attempt, attempt.id)
        assert persisted_attempt.validity_status == "valid"
        latest_validity = session.scalar(select(AttemptValidityEvent.validity_status).where(AttemptValidityEvent.attempt_id == attempt.id).order_by(AttemptValidityEvent.created_at.desc(), AttemptValidityEvent.id.desc()))
        assert latest_validity == "invalid"
    corrected = core.learning.resolve(
        action="correct_knowledge_unit", attempt_id=attempt.id,
        corrected_statement="Other people's choices are outside direct control; deliberate response remains available.",
        exercise=ExerciseSpecInput(exercise_type="explain_own_words", required_elements=["outside direct control", "deliberate response"]),
        idempotency_key="correct-1",
    )
    assert corrected["revision"] == 2
    assert corrected["review_status"] == "awaiting_question"
    with core.db.read() as session:
        revision = session.scalar(select(KnowledgeUnitRevision).where(KnowledgeUnitRevision.knowledge_unit_id == unit_id, KnowledgeUnitRevision.revision == 2))
        assert session.scalar(select(KnowledgeUnitSource).where(KnowledgeUnitSource.knowledge_unit_revision_id == revision.id)) is not None


def test_recall_returns_provenance(core):
    capture(core)
    recalled = core.queries.recall(query="control deliberate response")
    units = [row for row in recalled["results"] if row["entity_type"] == "knowledge_unit"]
    assert units
    assert units[0]["provenance_kind"] == "user_interpretation"
    assert units[0]["sources"][0]["title"] == "Notes on Meditations"
