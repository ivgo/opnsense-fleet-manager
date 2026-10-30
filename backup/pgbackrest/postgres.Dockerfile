# PostgreSQL 16 with pgBackRest for OPNsense Fleet Manager Enterprise
FROM postgres:16-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
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
    && pgbackrest --version

# pgBackRest configuration directory
RUN mkdir -p /etc/pgbackrest /var/log/pgbackrest /var/lib/pgbackrest /var/spool/pgbackrest/archive /var/spool/pgbackrest/archive/ofme /tmp/pgbackrest \
    && chown -R postgres:postgres /var/log/pgbackrest /var/lib/pgbackrest /var/spool/pgbackrest /tmp/pgbackrest \
    && chmod 750 /var/lib/pgbackrest

COPY backup/pgbackrest/pgbackrest.conf /etc/pgbackrest/pgbackrest.conf
RUN chown postgres:postgres /etc/pgbackrest/pgbackrest.conf

# Custom entrypoint to fix archive permissions on startup
COPY backup/pgbackrest/entrypoint-fix-permissions.sh /usr/local/bin/entrypoint-fix-permissions.sh
RUN chmod +x /usr/local/bin/entrypoint-fix-permissions.sh

ENTRYPOINT ["/usr/local/bin/entrypoint-fix-permissions.sh"]
CMD ["postgres"]