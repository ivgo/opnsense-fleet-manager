"""Celery application, queues and beat schedule.

Task names are declared once in :mod:`app.workers.dispatch`; the modules imported
below register exactly those names so that ``send_task`` calls from the API always
resolve.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

TASK_MODULES = [
    "app.workers.backups",
    "app.workers.compliance",
    "app.workers.devices",
    "app.workers.firmware",
    "app.workers.gitops",
    "app.workers.monitoring",
    "app.workers.policies",
    "app.workers.reports",
    "app.workers.sdwan",
    "app.workers.scheduler",
]

celery_app = Celery(
    "ofme",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=TASK_MODULES,
)

celery_app.conf.update(
    timezone="UTC",
    enable_utc=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_default_queue="ofme",
    task_default_exchange="ofme",
    task_default_routing_key="ofme",
    task_routes={
        "ofme.backups.*": {"queue": "ofme-backups"},
        "ofme.compliance.*": {"queue": "ofme-compliance"},
        "ofme.policies.*": {"queue": "ofme-policies"},
        "ofme.gitops.*": {"queue": "ofme-policies"},
        "ofme.monitoring.*": {"queue": "ofme-monitoring"},
        "ofme.devices.*": {"queue": "ofme-monitoring"},
        "ofme.sdwan.*": {"queue": "ofme-monitoring"},
        "ofme.firmware.*": {"queue": "ofme-firmware"},
        "ofme.tasks.*": {"queue": "ofme"},
    },
    task_acks_late=True,
    task_acks_on_failure_or_timeout=True,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    task_time_limit=settings.CELERY_TASK_TIME_LIMIT,
    task_soft_time_limit=settings.CELERY_TASK_SOFT_TIME_LIMIT,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=200,
    worker_send_task_events=True,
    task_send_sent_event=True,
    result_expires=24 * 3600,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": settings.CELERY_TASK_TIME_LIMIT + 300},
    beat_schedule={
        # Device liveness: promote stale heartbeats to OFFLINE.
        "heartbeat-timeout": {
            "task": "ofme.monitoring.heartbeat_timeout",
            "schedule": float(settings.HEARTBEAT_INTERVAL_SECONDS),
            "kwargs": {"params": {}},
            "options": {"expires": float(settings.HEARTBEAT_INTERVAL_SECONDS) * 0.9},
        },
        # Pull-based telemetry for devices without the agent.
        "poll-devices": {
            "task": "ofme.monitoring.collect",
            "schedule": 300.0,
            "kwargs": {"params": {"limit": 500}},
        },
        # SD-WAN SLA evaluation and steering.
        "sdwan-health-sweep": {
            "task": "ofme.sdwan.health_sweep",
            "schedule": 300.0,
            "kwargs": {"params": {}},
        },
        # Scheduled configuration backups.
        "nightly-backups": {
            "task": "ofme.backups.run_scheduled",
            "schedule": crontab(hour=2, minute=0),
            "kwargs": {"params": {"apply_retention": True}},
        },
        # Purge expired telemetry.
        "purge-metrics": {
            "task": "ofme.monitoring.purge_metrics",
            "schedule": crontab(hour=3, minute=30),
            "kwargs": {"params": {}},
        },
        # Certificate renewal window.
        "rotate-certificates": {
            "task": "ofme.devices.rotate_certificates",
            "schedule": crontab(hour=4, minute=0),
            "kwargs": {"params": {}},
        },
        # Drift detection against the latest deployed policy.
        "policy-drift-scan": {
            "task": "ofme.policies.drift_scan",
            "schedule": crontab(minute="*/30"),
            "kwargs": {"params": {}},
        },
        # Weekly compliance sweep over every framework.
        "weekly-compliance": {
            "task": "ofme.compliance.run",
            "schedule": crontab(hour=5, minute=0, day_of_week="monday"),
            "kwargs": {"params": {"all_frameworks": True}},
        },
        # Materialise tenant cron schedules every minute.
        "tenant-schedules": {
            "task": "ofme.tasks.custom",
            "schedule": 60.0,
            "kwargs": {"params": {"scheduler_tick": True}},
        },
    },
)


@celery_app.task(name="ofme.worker.ping", bind=True)
def ping(self) -> dict[str, str]:  # noqa: ANN001 - Celery task signature
    """Cheap liveness task used by readiness checks and smoke tests."""
    return {"status": "ok", "worker": self.request.hostname or "unknown", "version": settings.APP_VERSION}


__all__ = ["celery_app", "ping"]
