"""Structured JSON logging with request correlation."""

from __future__ import annotations

import logging
import sys
import uuid
from contextvars import ContextVar

import structlog

from app.core.config import settings

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")
tenant_id_ctx: ContextVar[str] = ContextVar("tenant_id", default="-")
user_id_ctx: ContextVar[str] = ContextVar("user_id", default="-")


def _add_context(_logger, _method, event_dict: dict) -> dict:
    event_dict.setdefault("request_id", request_id_ctx.get())
    event_dict.setdefault("tenant_id", tenant_id_ctx.get())
    event_dict.setdefault("user_id", user_id_ctx.get())
    event_dict.setdefault("service", settings.OTEL_SERVICE_NAME)
    event_dict.setdefault("env", settings.ENVIRONMENT)
    return event_dict


def configure_logging() -> None:
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_context,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer = (
        structlog.processors.JSONRenderer()
        if settings.LOG_JSON
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    for noisy in ("uvicorn.access", "botocore", "urllib3", "httpx", "ldap3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def new_request_id() -> str:
    return uuid.uuid4().hex


def get_logger(name: str = "ofme") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
