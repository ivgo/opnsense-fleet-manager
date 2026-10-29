# syntax=docker/dockerfile:1.7
# OFME API image. Built from the backend build context (see docker-compose.yml).

# Pinned to the Debian release we compile and link against: OpenLDAP 2.5
# (`libldap-2.5-0`). The floating `python:3.13-slim` tag moved to trixie, where
# the runtime library is `libldap2` / OpenLDAP 2.6.
FROM python:3.13-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libldap2-dev libsasl2-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip setuptools wheel \
    && /opt/venv/bin/pip install .


FROM python:3.13-slim-bookworm AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1 \
    APP_HOME=/app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libldap-2.5-0 ca-certificates tini fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 ofme \
    && useradd --system --uid 10001 --gid ofme --home-dir /app --shell /usr/sbin/nologin ofme

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=ofme:ofme app ./app
COPY --chown=ofme:ofme alembic ./alembic
COPY --chown=ofme:ofme alembic.ini ./
COPY --chown=ofme:ofme docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
    && mkdir -p /etc/ofme/pki /var/log/ofme /tmp/ofme-git /var/lib/ofme \
    && chown -R ofme:ofme /etc/ofme /var/log/ofme /tmp/ofme-git /var/lib/ofme /app

USER ofme

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=4).status == 200 else 1)"

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header"]
