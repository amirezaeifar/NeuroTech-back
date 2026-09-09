"""Application-facing errors without HTTP framework dependencies."""

from __future__ import annotations


class ApplicationError(Exception):
    code = "APPLICATION_ERROR"

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class ConflictError(ApplicationError):
    code = "CONFLICT"


class NotFoundError(ApplicationError):
    code = "NOT_FOUND"


class AuthenticationError(ApplicationError):
    code = "AUTHENTICATION_FAILED"


class AuthorizationError(ApplicationError):
    code = "FORBIDDEN"


class ValidationError(ApplicationError):
    code = "VALIDATION_ERROR"


class TemporarilyUnavailableError(ApplicationError):
    code = "AUTH_TEMPORARILY_UNAVAILABLE"


class RateLimitExceededError(ApplicationError):
    code = "RATE_LIMIT_EXCEEDED"

    def __init__(self, detail: str, retry_after: int) -> None:
        super().__init__(detail)
        self.retry_after = max(1, retry_after)
