class NoesisError(Exception):
    code = "noesis_error"

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class NotFound(NoesisError):
    code = "not_found"


class Conflict(NoesisError):
    code = "conflict"


class InvalidTransition(NoesisError):
    code = "invalid_transition"


class ValidationFailure(NoesisError):
    code = "validation_error"
