from sqlalchemy import select
from sqlalchemy.orm import Session

from noesis.persistence.models import Assessment, AssessmentStatusEvent, Attempt, AttemptValidityEvent, MemoryState, SchedulerTransition
from noesis.scheduler.interface import Scheduler


def rebuild_memory_state(session: Session, learner_id: str, unit_id: str, scheduler: Scheduler) -> MemoryState | None:
    for prior in session.scalars(select(SchedulerTransition).where(SchedulerTransition.learner_id == learner_id, SchedulerTransition.knowledge_unit_id == unit_id)):
        prior.active = False
    candidates = list(session.scalars(
        select(SchedulerTransition)
        .where(
            SchedulerTransition.learner_id == learner_id,
            SchedulerTransition.knowledge_unit_id == unit_id,
        )
        .order_by(SchedulerTransition.reviewed_at, SchedulerTransition.created_at)
    ))
    transitions = []
    for transition in candidates:
        assessment = session.get(Assessment, transition.assessment_id)
        attempt = session.get(Attempt, assessment.attempt_id)
        status = session.scalar(select(AssessmentStatusEvent.status).where(AssessmentStatusEvent.assessment_id == assessment.id).order_by(AssessmentStatusEvent.created_at.desc(), AssessmentStatusEvent.id.desc()).limit(1)) or assessment.status
        validity = session.scalar(select(AttemptValidityEvent.validity_status).where(AttemptValidityEvent.attempt_id == attempt.id).order_by(AttemptValidityEvent.created_at.desc(), AttemptValidityEvent.id.desc()).limit(1)) or attempt.validity_status
        if status == "accepted" and validity == "valid":
            transitions.append(transition)
    current = session.scalar(select(MemoryState).where(MemoryState.learner_id == learner_id, MemoryState.knowledge_unit_id == unit_id))
    if not transitions:
        if current:
            session.delete(current)
        return None
    state = None
    result = None
    failures = 0
    for transition in transitions:
        old_state = state or {}
        result = scheduler.schedule(state, transition.grade, transition.reviewed_at, transition.desired_retention)
        state = result.state
        transition.active = True
        transition.input_state = old_state
        transition.output_state = result.state
        transition.next_due_at = result.next_due
        if transition.grade == 1:
            failures += 1
        else:
            failures = 0
    assert result is not None
    if current is None:
        current = MemoryState(learner_id=learner_id, knowledge_unit_id=unit_id, scheduler_version=scheduler.version)
        session.add(current)
    current.scheduler_state = result.state
    current.last_review_at = transitions[-1].reviewed_at
    current.next_due_at = result.next_due
    current.scheduler_version = scheduler.version
    current.consecutive_failures = failures
    current.version = (current.version or 0) + 1
    return current
