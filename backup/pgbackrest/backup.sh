#!/bin/bash
# pgBackRest backup script for OPNsense Fleet Manager Enterprise
# Usage: ./backup.sh [full|diff|incr|info|verify]

set -e

STANZA="ofme"
BACKUP_TYPE="${1:-incr}"

echo "Starting pgBackRest $BACKUP_TYPE backup for stanza: $STANZA"

case "$BACKUP_TYPE" in
    full)
        pgbackrest --stanza=$STANZA --type=full backup
        ;;
    diff)
        pgbackrest --stanza=$STANZA --type=diff backup
        ;;
    incr)
        pgbackrest --stanza=$STANZA --type=incr backup
        ;;
    info)
        pgbackrest --stanza=$STANZA info
        ;;
    verify)
        pgbackrest --stanza=$STANZA verify
        ;;
    expire)
        pgbackrest --stanza=$STANZA expire
        ;;
    *)
        echo "Unknown backup type: $BACKUP_TYPE"
        echo "Usage: $0 [full|diff|incr|info|verify|expire]"
        exit 1
        ;;
esac

echo "Backup operation completed successfully"
