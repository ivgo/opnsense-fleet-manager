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
    && apt-get install -y --no-install-recommends \
        libldap-2.5-0 \
        ca-certificates \
        tini \
        fonts-dejavu-core \
        python3 \
        python3-pip \
        pkg-config \
        git \
        build-essential \
        libpq-dev \
        libssl-dev \
        zlib1g-dev \
        liblz4-dev \
        libzstd-dev \
        libbz2-dev \
        libreadline-dev \
        libxml2-dev \
        libyaml-dev \
        openssh-client \
        libpq5 \
        libssl3 \
        zlib1g \
        liblz4-1 \
        libzstd1 \
        libbz2-1.0 \
        libreadline8 \
        libxml2 \
        libyaml-0-2 \
        docker.io \
    && pip3 install --no-cache-dir --break-system-packages meson ninja \
    && git clone --depth 1 https://github.com/pgbackrest/pgbackrest.git /tmp/pgbackrest \
    && cd /tmp/pgbackrest \
    && git fetch --depth 1 origin tag release/2.54.2 \
    && git checkout release/2.54.2 \
    && meson setup build --prefix=/usr -Dlibssh2=disabled -Dlibzstd=enabled -Dfatal-errors=false \
    && ninja -C build \
    && ninja -C build install \
    && rm -rf /tmp/pgbackrest \
    && apt-get remove -y --purge python3-pip pkg-config git build-essential libpq-dev libssl-dev zlib1g-dev liblz4-dev libzstd-dev libbz2-dev libreadline-dev libxml2-dev libyaml-dev \
    && apt-get autoremove -y --purge \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /var/log/pgbackrest /var/spool/pgbackrest/archive /etc/pgbackrest /var/lib/pgbackrest \
    && groupadd --system --gid 999 postgres \
    && useradd --system --uid 999 --gid postgres --home-dir /var/lib/postgresql --shell /usr/sbin/nologin postgres \
    && chown -R postgres:postgres /var/log/pgbackrest /var/spool/pgbackrest /var/lib/pgbackrest \
    && chown root:root /etc/pgbackrest \
    && groupadd --system --gid 10001 ofme \
    && useradd --system --uid 10001 --gid ofme --home-dir /app --shell /usr/sbin/nologin ofme

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=ofme:ofme app ./app
COPY --chown=ofme:ofme alembic ./alembic
COPY --chown=ofme:ofme alembic.ini ./
COPY --chown=ofme:ofme docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY pgbackrest.conf /etc/pgbackrest/pgbackrest.conf

RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
    && mkdir -p /etc/ofme/pki /var/log/ofme /tmp/ofme-git /var/lib/ofme /var/lib/ofme/secrets \
    && chown -R ofme:ofme /etc/ofme /var/log/ofme /tmp/ofme-git /var/lib/ofme /app

USER ofme

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=4).status == 200 else 1)"

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header"]
