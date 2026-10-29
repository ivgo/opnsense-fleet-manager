"""Prometheus instrument definitions.

All collectors are registered once at import time against the default registry so
that ``/metrics`` exposes a stable contract for dashboards and alerting rules.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS_TOTAL = Counter(
    "ofme_http_requests_total",
    "HTTP requests processed by the API.",
    labelnames=("method", "route", "status"),
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "ofme_http_request_duration_seconds",
    "HTTP request latency in seconds.",
    labelnames=("method", "route"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

HTTP_REQUESTS_IN_FLIGHT = Gauge(
    "ofme_http_requests_in_flight",
    "Requests currently being served.",
)

HTTP_EXCEPTIONS_TOTAL = Counter(
    "ofme_http_exceptions_total",
    "Unhandled and domain exceptions raised while serving a request.",
    labelnames=("exception", "status"),
)

WS_CONNECTIONS = Gauge(
    "ofme_websocket_connections",
    "Currently connected WebSocket clients.",
)

WS_MESSAGES_TOTAL = Counter(
    "ofme_websocket_messages_total",
    "WebSocket frames sent to clients.",
    labelnames=("direction", "type"),
)

DEVICE_HEARTBEATS_TOTAL = Counter(
    "ofme_device_heartbeats_total",
    "Accepted device heartbeats.",
    labelnames=("result",),
)

DEVICE_AGENT_COMMANDS_TOTAL = Counter(
    "ofme_device_agent_commands_total",
    "Commands drained by device agents.",
)

JOBS_ENQUEUED_TOTAL = Counter(
    "ofme_jobs_enqueued_total",
    "Background jobs handed to Celery.",
    labelnames=("task",),
)

JOBS_FINISHED_TOTAL = Counter(
    "ofme_jobs_finished_total",
    "Background jobs that reached a terminal state.",
    labelnames=("task", "status"),
)

JOB_DURATION_SECONDS = Histogram(
    "ofme_job_duration_seconds",
    "Wall-clock duration of background jobs.",
    labelnames=("task",),
    buckets=(0.1, 0.5, 1.0, 5.0, 15.0, 30.0, 60.0, 300.0, 900.0, 1800.0),
)

COMPLIANCE_RUNS_TOTAL = Counter(
    "ofme_compliance_runs_total",
    "Compliance evaluations per framework and outcome.",
    labelnames=("framework", "status"),
)

COMPLIANCE_SCORE = Gauge(
    "ofme_compliance_score",
    "Score of the most recent compliance evaluation.",
    labelnames=("framework",),
)

BACKUPS_TOTAL = Counter(
    "ofme_backups_total",
    "Configuration backups by outcome.",
    labelnames=("result",),
)

BACKUPS_STORED_BYTES = Gauge(
    "ofme_backups_stored_bytes",
    "Total bytes of backup artifacts visible to the API process.",
)

POLICY_DRIFT_FINDINGS = Gauge(
    "ofme_policy_drift_findings",
    "Open drift findings across managed devices.",
)

AUDIT_CHAIN_VALID = Gauge(
    "ofme_audit_chain_valid",
    "1 when the most recent audit chain verification succeeded, else 0.",
)

CACHE_OPERATIONS_TOTAL = Counter(
    "ofme_cache_operations_total",
    "Redis operations issued by the API.",
    labelnames=("operation", "result"),
)

RATE_LIMITED_TOTAL = Counter(
    "ofme_rate_limited_total",
    "Requests rejected by the rate limiter.",
    labelnames=("scope",),
)


def observe_job(task: str, status: str, duration_seconds: float) -> None:
    """Record a finished background job."""
    JOBS_FINISHED_TOTAL.labels(task=task, status=status).inc()
    JOB_DURATION_SECONDS.labels(task=task).observe(max(duration_seconds, 0.0))


__all__ = [
    "AUDIT_CHAIN_VALID",
    "BACKUPS_STORED_BYTES",
    "BACKUPS_TOTAL",
    "CACHE_OPERATIONS_TOTAL",
    "COMPLIANCE_RUNS_TOTAL",
    "COMPLIANCE_SCORE",
    "DEVICE_AGENT_COMMANDS_TOTAL",
    "DEVICE_HEARTBEATS_TOTAL",
    "HTTP_EXCEPTIONS_TOTAL",
    "HTTP_REQUESTS_IN_FLIGHT",
    "HTTP_REQUESTS_TOTAL",
    "HTTP_REQUEST_DURATION_SECONDS",
    "JOB_DURATION_SECONDS",
    "JOBS_ENQUEUED_TOTAL",
    "JOBS_FINISHED_TOTAL",
    "POLICY_DRIFT_FINDINGS",
    "RATE_LIMITED_TOTAL",
    "WS_CONNECTIONS",
    "WS_MESSAGES_TOTAL",
    "observe_job",
]
