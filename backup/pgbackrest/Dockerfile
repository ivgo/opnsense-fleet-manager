# pgBackRest container for OPNsense Fleet Manager Enterprise
# Debian bookworm base so the package index resolves reliably (the Alpine
# edge/community mirrors occasionally refuse apk add with "unable to select
# packages"). pgBackRest 4.0.x is built from source against the same OpenSSL
# and libpq the database service links against.
FROM debian:bookworm-slim

RUN set -eux \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        python3 \
        python3-pip \
        pkg-config \
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
    && git clone --depth 1 https://github.com/pgbackrest/pgbackrest.git /tmp/pgbackrest \
    && cd /tmp/pgbackrest \
    && git fetch --depth 1 origin tag release/2.54.2 \
    && git checkout release/2.54.2 \
    && pip install --no-cache-dir --break-system-packages meson ninja \
    && meson setup build --prefix=/usr \
        -Dlibssh2=disabled -Dlibzstd=enabled -Dfatal-errors=false \
    && ninja -C build \
    && ninja -C build install \
    && rm -rf /tmp/pgbackrest \
    && apt-get remove -y --purge curl git python3-pip pkg-config build-essential libpq-dev libssl-dev zlib1g-dev liblz4-dev libzstd-dev libbz2-dev libreadline-dev libxml2-dev libyaml-dev \
    && apt-get install -y --no-install-recommends libpq5 libssl3 zlib1g liblz4-1 libzstd1 libbz2-1.0 libreadline8 libxml2 libyaml-0-2 \
    && apt-get autoremove -y --purge \
    && rm -rf /var/lib/apt/lists/* \
    && pgbackrest --version

ENV PGBACKREST_STANZA=ofme
ENV PGBACKREST_LOG_PATH=/var/log/pgbackrest
ENV PGBACKREST_LOG_LEVEL_CONSOLE=info
ENV PGBACKREST_LOG_LEVEL_FILE=detail

RUN groupadd -r postgres && useradd -r -g postgres postgres \
    && mkdir -p /var/log/pgbackrest \
    /var/spool/pgbackrest/archive \
    /etc/pgbackrest \
    /var/lib/pgbackrest \
    && chown -R postgres:postgres /var/log/pgbackrest /var/spool/pgbackrest /etc/pgbackrest /var/lib/pgbackrest

COPY backup/pgbackrest/pgbackrest.conf /etc/pgbackrest/pgbackrest.conf
RUN chown postgres:postgres /etc/pgbackrest/pgbackrest.conf

USER postgres

EXPOSE 1985

CMD ["pgbackrest", "--stanza=ofme", "info"]