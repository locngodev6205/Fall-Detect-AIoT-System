#!/bin/sh
set -eu
umask 077
work_dir=$(mktemp -d)
trap 'rm -rf "$work_dir"' EXIT HUP INT TERM

case "${ANNHA_DB_TARGET:-}" in
  local)
    [ "${PGHOST:-}" = postgres ] && [ "${PGDATABASE:-}" = annha_design ] || {
      echo 'Local tools must use the dedicated postgres/annha_design target.' >&2; exit 2;
    }
    PGPASSWORD=$(cat "${ANNHA_PASSWORD_FILE:?Missing local password secret}")
    export PGPASSWORD
    ;;
  neon)
    [ "${PGSERVICE:-}" = annha_neon_migration ] || { echo 'Unexpected Neon service name.' >&2; exit 2; }
    [ -r "${PGSERVICEFILE:?Missing Neon service secret}" ] || exit 2
    if grep -Eq 'REPLACE_|CHANGE_ME' "$PGSERVICEFILE" "${ANNHA_PGPASS_FILE:?Missing Neon password secret}"; then
      echo 'Fill the ignored Neon secret files before connecting.' >&2; exit 2
    fi
    # libpq rejects an overly readable pgpass. Compose file secrets may be 0444.
    cp "$ANNHA_PGPASS_FILE" "$work_dir/pgpass"
    chmod 0600 "$work_dir/pgpass"
    PGPASSFILE=$work_dir/pgpass
    export PGPASSFILE
    ;;
  *) echo 'ANNHA_DB_TARGET must be local or neon.' >&2; exit 2 ;;
esac

case "${1:-inspect}" in
  bootstrap)
    # Combine both DDL files into ONE transaction, including CREATE ROLE.
    # No rerun-on-existing-schema shortcut: refuse instead of hiding a drifted schema.
    for file in 001_schema.sql 002_security.sql 005_email_notifications.sql 007_home_archiving.sql 008_archived_home_notifications.sql; do
      sed '/^BEGIN;$/d; /^COMMIT;$/d' "/opt/annha/schema/$file" >> "$work_dir/bootstrap.sql"
    done
    psql -X -q -v ON_ERROR_STOP=1 --single-transaction -f "$work_dir/bootstrap.sql"
    echo 'Schema and security created atomically. Existing schema/roles are never reset.'
    ;;
  verify)
    [ "$ANNHA_DB_TARGET" = local ] || { echo 'Fixture verification is restricted to the local lab.' >&2; exit 2; }
    psql -X -qAt -v ON_ERROR_STOP=1 -f /opt/annha/schema/003_verify.sql
    psql -X -qAt -v ON_ERROR_STOP=1 -f /opt/annha/schema/006_verify_email.sql
    ;;
  inspect)
    psql -X -v ON_ERROR_STOP=1 -f /opt/annha/schema/004_inspect.sql
    ;;
  upgrade-email)
    psql -X -q -v ON_ERROR_STOP=1 -f /opt/annha/schema/005_email_notifications.sql
    echo 'Email notification schema upgraded; existing data retained.'
    ;;
  console)
    psql -X -v ON_ERROR_STOP=1
    ;;
  *) echo 'Supported commands: bootstrap, verify, inspect, upgrade-email, console.' >&2; exit 2 ;;
esac
