from enum import StrEnum


class Lifecycle(StrEnum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    MAINTENANCE = "maintenance"
    ARCHIVED = "archived"


class Validity(StrEnum):
    VALID = "valid"
    INVALID = "invalid"
    QUESTIONED = "questioned"


class EdgeType(StrEnum):
    PREREQUISITE_OF = "prerequisite_of"
    CONTRASTS_WITH = "contrasts_with"
    RELATED_TO = "related_to"


class ProposalStatus(StrEnum):
    PENDING = "pending"
    COMMITTED = "committed"
    EXPIRED = "expired"


class SessionStatus(StrEnum):
    CREATED = "created"
    AWAITING_QUESTION = "awaiting_question"
    AWAITING_ANSWER = "awaiting_answer"
    AWAITING_RESOLUTION = "awaiting_resolution"
    COMPLETE = "complete"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class AssessmentStatus(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    DISPUTED = "disputed"
    SUPERSEDED = "superseded"
    UNGRADABLE = "ungradable"


class RecallOutcome(StrEnum):
    FAILED = "failed"
    DIFFICULT = "difficult"
    SUCCESSFUL = "successful"
    EFFORTLESS = "effortless"
    UNGRADABLE = "ungradable"

