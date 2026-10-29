# Test agent for OFME — a minimal stand-in for the real os-fleet-agent plugin.
#
# It speaks the same HTTP contract the production agent uses (see
# backend/app/api/v1/endpoints/agent.py) so it can be enrolled and exercised
# end-to-end against a running stack:
#
#   GET  /agent/bootstrap?token=...     -> BootstrapPackage
#   POST /agent/enroll                  -> EnrollmentResponse (device cert + CA)
#   POST /agent/heartbeat               -> HeartbeatResponse
#   GET  /agent/config                  -> desired configuration + config_hash
#   GET  /agent/commands                -> CommandBatch
#   POST /agent/telemetry               -> HeartbeatResponse
#
# The container is driven by the env vars OFME_BASE_URL and ENROLLMENT_TOKEN.
# After enrollment it holds the device cert + CA in /etc/agent/certs and
# authenticates every subsequent request with the client certificate.

FROM python:3.13-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY agent.py /app/agent.py
RUN pip install --no-cache-dir httpx==0.28.1

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8080
CMD ["python", "/app/agent.py"]