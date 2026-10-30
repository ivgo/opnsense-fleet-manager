#!/bin/bash
# Fix pgBackRest directory permissions on startup, then run stanza-create

# Ensure archive directory exists and has correct ownership
mkdir -p /var/lib/pgbackrest/archive/ofme
chown -R postgres:postgres /var/lib/pgbackrest/archive
chmod -R g+rwX /var/lib/pgbackrest/archive

# Ensure backup directory has correct ownership (stanza-create creates root-owned files)
mkdir -p /var/lib/pgbackrest/backup/ofme
chown -R postgres:postgres /var/lib/pgbackrest/backup
chmod -R g+rwX /var/lib/pgbackrest/backup

# Fix log directory permissions
chown -R postgres:postgres /var/log/pgbackrest
chmod -R g+rwX /var/log/pgbackrest

# Call the original postgres entrypoint (waits for PG to be ready)
exec docker-entrypoint.sh "$@"