from __future__ import annotations

import logging
import json
from typing import Any
from uuid import uuid4

from mcp.server.mcpserver import MCPServer
from pydantic import ValidationError

from noesis.application.contracts import AssessmentInput, CaptureProposalInput, CommitCaptureInput, ExerciseSpecInput
from noesis.application.service import Noesis
from noesis.domain.errors import NoesisError


core = Noesis()
server = MCPServer(name="noesis", description="Deterministic local-first learning record", version="0.1.0")
logger = logging.getLogger("noesis.mcp")


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "level": record.levelname.lower(), "logger": record.name,
            "operation": getattr(record, "operation", None),
            "correlation_id": getattr(record, "correlation_id", None),
            "phase": record.getMessage(), "code": getattr(record, "code", None),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"))


_handler = logging.StreamHandler()
_handler.setFormatter(JsonFormatter())
logger.handlers.clear()
logger.addHandler(_handler)
logger.setLevel(logging.INFO)
logger.propagate = False


def _log(level: int, operation: str, correlation_id: str, phase: str, code: str | None = None) -> None:
    logger.log(level, phase, extra={"operation": operation, "correlation_id": correlation_id, "code": code})


def _call(operation: str, _correlation_id: str | None, fn, *args, **kwargs) -> dict[str, Any]:
    correlation_id = _correlation_id or str(uuid4())
    _log(logging.INFO, operation, correlation_id, "start")
    try:
        result = {"success": True, "correlation_id": correlation_id, "data": fn(*args, **kwargs)}
        _log(logging.INFO, operation, correlation_id, "complete")
        return result
    except ValidationError as error:
        _log(logging.WARNING, operation, correlation_id, "error", "validation_error")
        return {"success": False, "correlation_id": correlation_id, "error": {"code": "validation_error", "message": "Invalid input", "details": error.errors(include_url=False)}}
    except NoesisError as error:
        _log(logging.WARNING, operation, correlation_id, "error", error.code)
        return {"success": False, "correlation_id": correlation_id, "error": {"code": error.code, "message": str(error), "details": error.details}}
    except Exception:
        logger.exception("error", extra={"operation": operation, "correlation_id": correlation_id, "code": "internal_error"})
        return {"success": False, "correlation_id": correlation_id, "error": {"code": "internal_error", "message": "Internal Noesis error; inspect local logs using the correlation ID."}}


@server.tool()
def propose_capture(proposal: dict[str, Any], idempotency_key: str, actor: str = "hermes", correlation_id: str | None = None) -> dict[str, Any]:
    """Validate and persist an inactive explicit capture proposal; never activates learning material."""
    correlation_id = correlation_id or str(uuid4())
    return _call("propose_capture", correlation_id, lambda: core.capture.propose(CaptureProposalInput.model_validate(proposal), actor=actor, idempotency_key=idempotency_key, correlation_id=correlation_id))


@server.tool()
def commit_capture(proposal_id: str, decisions: list[dict[str, Any]], idempotency_key: str,
                   actor: str = "user", correlation_id: str | None = None) -> dict[str, Any]:
    """Transactionally commit only user-approved or edited capture proposal elements."""
    correlation_id = correlation_id or str(uuid4())
    data = {"proposal_id": proposal_id, "decisions": decisions, "idempotency_key": idempotency_key, "actor": actor, "correlation_id": correlation_id}
    return _call("commit_capture", correlation_id, lambda: core.capture.commit(CommitCaptureInput.model_validate(data)))


@server.tool()
def start_review(idempotency_key: str, learner_id: str = "default", review_session_id: str | None = None,
                 question_text: str | None = None, model_id: str | None = None,
                 prompt_version: str | None = None, generation_context_ref: str | None = None,
                 origin_metadata: dict[str, Any] | None = None, correlation_id: str | None = None) -> dict[str, Any]:
    """Create/resume a durable review or record the exact Hermes-generated question for its current item."""
    correlation_id = correlation_id or str(uuid4())
    return _call("start_review", correlation_id, core.reviews.start, learner_id=learner_id, session_id=review_session_id, question_text=question_text,
                 model_id=model_id, prompt_version=prompt_version, generation_context_ref=generation_context_ref,
                 origin_metadata=origin_metadata, correlation_id=correlation_id, idempotency_key=idempotency_key)


@server.tool()
def submit_attempt(review_session_id: str, exact_response: str, assessment: dict[str, Any], idempotency_key: str,
                   hints_used: list[str] | None = None, latency_ms: int | None = None,
                   correlation_id: str | None = None) -> dict[str, Any]:
    """Record immutable answer evidence and conditionally apply the deterministic scheduler transition."""
    correlation_id = correlation_id or str(uuid4())
    return _call("submit_attempt", correlation_id, lambda: core.reviews.submit(review_session_id=review_session_id, exact_response=exact_response,
                 assessment=AssessmentInput.model_validate(assessment), hints_used=hints_used, latency_ms=latency_ms,
                 correlation_id=correlation_id, idempotency_key=idempotency_key))


@server.tool()
def resolve_learning_issue(action: str, idempotency_key: str, assessment_id: str | None = None,
                           attempt_id: str | None = None, replacement: dict[str, Any] | None = None,
                           self_grade: str | None = None, corrected_statement: str | None = None,
                           exercise: dict[str, Any] | None = None, correlation_id: str | None = None) -> dict[str, Any]:
    """Resolve a disputed grade, invalid/bad question, or corrected knowledge unit without deleting history."""
    correlation_id = correlation_id or str(uuid4())
    return _call("resolve_learning_issue", correlation_id, lambda: core.learning.resolve(action=action, assessment_id=assessment_id, attempt_id=attempt_id,
                 replacement=AssessmentInput.model_validate(replacement) if replacement else None,
                 self_grade=self_grade, corrected_statement=corrected_statement,
                 exercise=ExerciseSpecInput.model_validate(exercise) if exercise else None,
                 correlation_id=correlation_id, idempotency_key=idempotency_key))


@server.tool()
def update_learning_state(idempotency_key: str, knowledge_unit_id: str | None = None, learner_id: str = "default",
                          policy_updates: dict[str, Any] | None = None, importance: float | None = None,
                          desired_retention: float | None = None, lifecycle_status: str | None = None,
                          expected_version: int | None = None, correlation_id: str | None = None) -> dict[str, Any]:
    """Change priority or lifecycle policy while preserving memory strength and review history."""
    correlation_id = correlation_id or str(uuid4())
    return _call("update_learning_state", correlation_id, core.learning.update_state, knowledge_unit_id=knowledge_unit_id, learner_id=learner_id,
                 policy_updates=policy_updates, importance=importance,
                 desired_retention=desired_retention, lifecycle_status=lifecycle_status, expected_version=expected_version,
                 correlation_id=correlation_id, idempotency_key=idempotency_key)


@server.tool()
def recall_context(query: str, learner_id: str = "default", limit: int = 10,
                   include_suspended: bool = False, correlation_id: str | None = None) -> dict[str, Any]:
    """Retrieve lexical learning evidence and provenance for Hermes to synthesize into an answer."""
    correlation_id = correlation_id or str(uuid4())
    return _call("recall_context", correlation_id, core.queries.recall, query=query, learner_id=learner_id, limit=limit, include_suspended=include_suspended)


@server.tool()
def get_progress(learner_id: str = "default", correlation_id: str | None = None) -> dict[str, Any]:
    """Return due load, lifecycle counts, fragile units, assessments, and open sessions."""
    correlation_id = correlation_id or str(uuid4())
    return _call("get_progress", correlation_id, core.queries.progress, learner_id=learner_id)


def main() -> None:
    server.run(transport="stdio")
