#!/bin/bash
# pgBackRest restore script for OPNsense Fleet Manager Enterprise
# Usage: ./restore.sh [latest|<backup-id>]

set -e

STANZA="ofme"
BACKUP_ID="${1:-latest}"

echo "Starting pgBackRest restore for stanza: $STANZA"

if [ "$BACKUP_ID" = "latest" ]; then
    echo "Restoring latest backup..."
    pgbackrest --stanza=$STANZA restore --type=latest
else
    echo "Restoring backup: $BACKUP_ID"
    pgbackrest --stanza=$STANZA restore --set="$BACKUP_ID"
fi

echo "Restore operation completed successfully"