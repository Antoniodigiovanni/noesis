from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from noesis.domain.errors import Conflict
from noesis.persistence.models import Event, IdempotencyRecord, LearnerPolicy


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", " ", value).strip()


def content_hash(value: str | None) -> str:
    return hashlib.sha256(normalize_text(value).encode("utf-8")).hexdigest()


def request_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def get_idempotent(session: Session, operation: str, key: str, payload: Any) -> dict[str, Any] | None:
    row = session.scalar(select(IdempotencyRecord).where(IdempotencyRecord.operation == operation, IdempotencyRecord.key == key))
    if row is None:
        return None
    if row.request_hash != request_hash(payload):
        raise Conflict("idempotency key was already used with different input", {"operation": operation, "idempotency_key": key})
    return row.response


def save_idempotent(session: Session, operation: str, key: str, payload: Any, response: dict[str, Any]) -> None:
    session.add(IdempotencyRecord(operation=operation, key=key, request_hash=request_hash(payload), response=response))


def policy_for(session: Session, learner_id: str) -> LearnerPolicy:
    policy = session.get(LearnerPolicy, learner_id)
    if policy is None:
        policy = LearnerPolicy(learner_id=learner_id)
        session.add(policy)
        session.flush()
    return policy


def add_event(
    session: Session, *, aggregate_type: str, aggregate_id: str, event_type: str,
    actor: str, correlation_id: str, payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None, model_id: str | None = None,
    prompt_version: str | None = None, source_system: str = "noesis",
) -> None:
    session.add(Event(
        aggregate_type=aggregate_type, aggregate_id=aggregate_id, event_type=event_type,
        payload=payload or {}, actor=actor, source_system=source_system,
        correlation_id=correlation_id, idempotency_key=idempotency_key,
        model_id=model_id, prompt_version=prompt_version,
    ))
