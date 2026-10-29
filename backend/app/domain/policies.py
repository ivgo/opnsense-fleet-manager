"""Domain policies: pure functions encoding business rules independent of frameworks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.domain.value_objects import Severity


@dataclass(frozen=True, slots=True)
class DeploymentGate:
    """Rules that decide whether a policy may be applied to production."""

    environment: str
    change_request_approved: bool
    required_approvals: int
    approvals: int
    validation_passed: bool
    has_drift: bool = False

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    def violations(self) -> list[str]:
        problems: list[str] = []
        if not self.validation_passed:
            problems.append("policy failed validation")
        if self.is_production:
            if not self.change_request_approved:
                problems.append("production deployment requires an approved change request")
            if self.approvals < self.required_approvals:
                problems.append(f"insufficient approvals: {self.approvals}/{self.required_approvals}")
        return problems

    @property
    def allowed(self) -> bool:
        return not self.violations()


@dataclass(frozen=True, slots=True)
class HeartbeatWindow:
    offline_after_seconds: int

    def is_offline(self, last_heartbeat: datetime | None, now: datetime) -> bool:
        if last_heartbeat is None:
            return True
        return now - last_heartbeat > timedelta(seconds=self.offline_after_seconds)


@dataclass(frozen=True, slots=True)
class LicensePolicy:
    device_limit: int
    device_count: int
    grace_ratio: float = 0.0

    @property
    def at_limit(self) -> bool:
        return self.device_count >= self.device_limit

    @property
    def utilisation(self) -> float:
        if self.device_limit <= 0:
            return 1.0
        return min(self.device_count / self.device_limit, 1.0)

    def allows(self, additional: int = 1) -> bool:
        return self.device_count + additional <= self.device_limit


@dataclass(frozen=True, slots=True)
class CertificatePolicy:
    renew_before_days: int

    def needs_rotation(self, valid_to: datetime, now: datetime) -> bool:
        return valid_to - now <= timedelta(days=self.renew_before_days)


@dataclass(frozen=True, slots=True)
class SlaThreshold:
    latency_ms: float
    loss_pct: float
    jitter_ms: float = 30.0

    def violated(
        self, latency_ms: float | None, loss_pct: float | None, jitter_ms: float | None
    ) -> list[str]:
        problems: list[str] = []
        if latency_ms is not None and latency_ms > self.latency_ms:
            problems.append("latency")
        if loss_pct is not None and loss_pct > self.loss_pct:
            problems.append("loss")
        if jitter_ms is not None and jitter_ms > self.jitter_ms:
            problems.append("jitter")
        return problems


def aggregate_severity(values: list[str]) -> str:
    return Severity.highest(values)
