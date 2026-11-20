#!/bin/bash
# libpq credentials are supplied via protected PGSERVICEFILE / PGPASSFILE.
set -euo pipefail
umask 077
: "${PGSERVICE:?protected production libpq service required}"
: "${PGSERVICEFILE:?protected libpq service file required}"
action=${1:?usage: database.sh backup OUTPUT | restore-check BACKUP TEST_SERVICE TEST_DATABASE}
case "$action" in
backup)
  output=${2:?new backup filename required}
  [[ ! -e "$output" ]] || { echo 'Refusing to overwrite backup' >&2; exit 1; }
  pg_dump --format=custom --no-owner --no-acl --file="$output"
  pg_restore --list "$output" >/dev/null
  sha256sum "$output" > "$output.sha256"
  echo 'Backup created; restore verification still required.'
  ;;
restore-check)
  backup=${2:?backup required}; test_service=${3:?isolated libpq test service required}; test_db=${4:?expected isolated database name required}
  [[ "$test_service" != "${PGSERVICE:-}" ]] || { echo 'Restore service must differ from production' >&2; exit 1; }
  [[ "$test_db" =~ ^noesis_restore_[a-zA-Z0-9_]+$ ]] || { echo 'Use a dedicated noesis_restore_* database' >&2; exit 1; }
  source_database=$(psql -XAtqc 'SELECT current_database()')
  [[ "$test_db" != "$source_database" ]] || { echo 'Restore target must differ from source database' >&2; exit 1; }
  actual=$(PGSERVICE="$test_service" psql -XAtqc 'SELECT current_database()')
  [[ "$actual" == "$test_db" ]] || exit 1
  tables=$(PGSERVICE="$test_service" psql -XAtqc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
  [[ "$tables" == 0 ]] || { echo 'Restore target must be empty' >&2; exit 1; }
  echo "Restore target: $test_db (empty isolated database)"
  PGSERVICE="$test_service" pg_restore --exit-on-error --single-transaction --no-owner --no-acl --dbname="service=$test_service" "$backup"
  PGSERVICE="$test_service" psql -Xv ON_ERROR_STOP=1 -c 'SELECT version_num FROM alembic_version' -c 'SELECT count(*) AS review_count FROM app_review_evidence' -c 'SELECT count(*) AS card_count FROM app_cards'
  echo 'Database restore check passed. Run authenticated application acceptance against this isolated database before promotion.'
  ;;
*) exit 2 ;;
esac
