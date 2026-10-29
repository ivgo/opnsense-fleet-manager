"""OpenTelemetry bootstrap: tracing for the API process.

Instrumentation is entirely optional. When ``OTEL_ENABLED`` is false the helpers are
no-ops, which keeps local development free of an OTLP collector dependency.
"""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger("ofme.otel")

_initialised = False


def setup_tracing(app: Any) -> None:
    """Configure the tracer provider and instrument the FastAPI application."""
    global _initialised
    if _initialised or not settings.OTEL_ENABLED:
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:  # pragma: no cover - optional dependency
        log.warning("otel.import_failed", error=str(exc))
        return

    resource = Resource.create(
        {
            "service.name": settings.OTEL_SERVICE_NAME,
            "service.version": settings.APP_VERSION,
            "deployment.environment": settings.ENVIRONMENT,
        }
    )
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(
        endpoint=f"{settings.OTEL_EXPORTER_OTLP_ENDPOINT.rstrip('/')}/v1/traces",
        timeout=10,
    )
    provider.add_span_processor(BatchSpanProcessor(exporter, max_queue_size=2048, max_export_batch_size=512))
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=provider,
        excluded_urls="health/live,health/ready,metrics",
    )

    _initialised = True
    log.info(
        "otel.configured",
        endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT,
        service=settings.OTEL_SERVICE_NAME,
    )


def get_tracer(name: str = "ofme") -> Any:
    """Return a tracer; a no-op tracer when tracing is disabled."""
    from opentelemetry import trace

    return trace.get_tracer(name)


def current_trace_id() -> str | None:
    """Hex trace id of the active span, for log correlation."""
    try:
        from opentelemetry import trace

        span_context = trace.get_current_span().get_span_context()
        if not span_context.is_valid:
            return None
        return format(span_context.trace_id, "032x")
    except Exception:  # noqa: BLE001 - diagnostics must never fail a request
        return None


__all__ = ["current_trace_id", "get_tracer", "setup_tracing"]
