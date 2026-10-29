"""Domain/application exception hierarchy mapped to HTTP responses in `main.py`."""

from __future__ import annotations

from typing import Any


class OFMEError(Exception):
    """Base class for all application errors."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, details: Any | None = None, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details
        if code:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details is not None:
            payload["details"] = self.details
        return payload


class ValidationError(OFMEError):
    status_code = 422
    code = "validation_error"


class NotFoundError(OFMEError):
    status_code = 404
    code = "not_found"


class ConflictError(OFMEError):
    status_code = 409
    code = "conflict"


class BadRequestError(OFMEError):
    status_code = 400
    code = "bad_request"


class AuthenticationError(OFMEError):
    status_code = 401
    code = "unauthenticated"


class MFARequiredError(AuthenticationError):
    code = "mfa_required"


class PermissionDeniedError(OFMEError):
    status_code = 403
    code = "permission_denied"


class TenantIsolationError(PermissionDeniedError):
    code = "tenant_isolation_violation"


class LicenseLimitError(OFMEError):
    status_code = 402
    code = "license_limit"


class RateLimitError(OFMEError):
    status_code = 429
    code = "rate_limited"


class UpstreamError(OFMEError):
    status_code = 502
    code = "upstream_error"


class PolicyValidationError(OFMEError):
    status_code = 422
    code = "policy_validation_failed"


class DeploymentError(OFMEError):
    status_code = 500
    code = "deployment_failed"
