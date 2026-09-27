#!/usr/bin/env bash
set -euo pipefail
umask 077

source_arg=${1:-latest}
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
install_dir=${NOESIS_INSTALL_DIR:-$(dirname "$script_dir")}
repo=${NOESIS_RELEASE_REPOSITORY:-Antoniodigiovanni/noesis}
staging= new_dir= previous= backup= switched= migration_started= had_database=

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
valid_tag() { [[ "$1" =~ ^v[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9][A-Za-z0-9.-]*)?$ ]]; }
manifest_value() { awk -F= -v key="$2" '$1 == key {sub(/^[^=]*=/, ""); print; exit}' "$1"; }

cleanup() {
  local status=$?
  if (( status != 0 )) && [[ -n "$migration_started" ]]; then
    printf 'Update failed; restoring the previous release and database.\n' >&2
    if [[ -n "$switched" ]]; then
      if [[ -n "$previous" ]]; then
        ln -sfn "$previous" "$install_dir/releases/.rollback-link"
        mv -Tf "$install_dir/releases/.rollback-link" "$install_dir/releases/current"
      else
        rm -f "$install_dir/releases/current"
      fi
    fi
    rm -f "$install_dir/state/noesis.db"{,-wal,-shm}
    if [[ -n "$had_database" && -n "$backup" && -f "$backup" ]]; then
      cp -p "$backup" "$install_dir/state/noesis.db"
    fi
  fi
  if (( status != 0 )) && [[ -n "$new_dir" ]]; then rm -rf "$new_dir"; fi
  [[ -z "$staging" ]] || rm -rf "$staging"
  exit "$status"
}
trap cleanup EXIT

for command in awk cp flock install ln mktemp mv python3 sha256sum tar uv; do
  command -v "$command" >/dev/null || die "required command not found: $command"
done
[[ $(id -u) -ne 0 ]] || die 'run as the unprivileged Noesis deployment account, not root'
[[ "$install_dir" != *[[:space:]]* ]] || die 'installation path cannot contain whitespace'
install -d -m 0755 "$install_dir" "$install_dir/releases" "$install_dir/bin" "$install_dir/deploy"
install -d -m 0700 "$install_dir/state" "$install_dir/cache" "$install_dir/backups"
touch "$install_dir/state/runtime.lock" "$install_dir/state/update.lock"
chmod 0600 "$install_dir/state/runtime.lock" "$install_dir/state/update.lock"
exec 8>"$install_dir/state/update.lock"
flock -n 8 || die 'another Noesis update is running'
staging=$(mktemp -d)

if [[ "$source_arg" == latest || "$source_arg" == v* ]]; then
  command -v curl >/dev/null || die 'curl is required to download a release'
  [[ "$repo" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || die 'invalid release repository'
  if [[ "$source_arg" == latest ]]; then
    tag=$(curl -fsSL --retry 3 "https://api.github.com/repos/$repo/releases/latest" | \
      python3 -c 'import json,sys; print(json.load(sys.stdin)["tag_name"])')
  else
    tag=$source_arg
  fi
  valid_tag "$tag" || die "invalid release tag: $tag"
  name="noesis-$tag-native.tar.gz"
  base="https://github.com/$repo/releases/download/$tag/$name"
  curl -fL --retry 3 -o "$staging/$name" "$base"
  curl -fL --retry 3 -o "$staging/$name.sha256" "$base.sha256"
  archive="$staging/$name"
else
  archive=$source_arg
  [[ -f "$archive" && -f "$archive.sha256" ]] || die 'archive and matching .sha256 are required'
  cp -p -- "$archive" "$archive.sha256" "$staging/"
  archive="$staging/$(basename -- "$archive")"
fi

name=$(basename -- "$archive")
[[ "$name" =~ ^noesis-(v[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9][A-Za-z0-9.-]*)?)-native\.tar\.gz$ ]] || die 'invalid archive name'
tag=${BASH_REMATCH[1]}
[[ $(wc -l < "$archive.sha256") -eq 1 ]] || die 'checksum must contain exactly one line'
[[ $(awk '{print $2}' "$archive.sha256") == "$name" ]] || die 'checksum filename mismatch'
(cd "$staging" && sha256sum -c -- "$name.sha256") || die 'checksum verification failed'

python3 - "$archive" <<'PY'
import sys, tarfile
from pathlib import PurePosixPath
with tarfile.open(sys.argv[1], "r:gz") as archive:
    seen = set()
    for member in archive:
        path = PurePosixPath(member.name)
        if (path.is_absolute() or ".." in path.parts or not path.parts
                or path.parts[0] != "noesis" or member.name in seen
                or not (member.isfile() or member.isdir())):
            raise SystemExit(f"unsafe archive member: {member.name}")
        seen.add(member.name)
PY
mkdir "$staging/unpacked"
tar -xzf "$archive" -C "$staging/unpacked" --no-same-owner --no-same-permissions
payload="$staging/unpacked/noesis"
[[ -f "$payload/pyproject.toml" && -f "$payload/uv.lock" && -f "$payload/alembic.ini" && \
   -f "$payload/migrations/env.py" && -f "$payload/deploy/noesis-mcp" && \
   -f "$payload/deploy/mcp-smoke.py" && -f "$payload/deploy/prepare-legacy.py" && \
   -f "$payload/release.env" ]] || die 'incomplete release archive'
[[ $(manifest_value "$payload/release.env" RELEASE_TAG) == "$tag" ]] || die 'release tag mismatch'
version=$(python3 - "$payload/pyproject.toml" <<'PY'
import sys,tomllib
with open(sys.argv[1], "rb") as handle: print(tomllib.load(handle)["project"]["version"])
PY
)
[[ "v$version" == "$tag" ]] || die 'package version does not match release tag'
expected_lock=$(manifest_value "$payload/release.env" UV_LOCK_SHA256)
actual_lock=$(sha256sum "$payload/uv.lock" | awk '{print $1}')
[[ -n "$expected_lock" && "$actual_lock" == "$expected_lock" ]] || die 'lock-file digest mismatch'
[[ ! -e "$install_dir/releases/$tag" ]] || die "release $tag is already installed"

new_dir="$install_dir/releases/$tag"
install -d -m 0755 "$new_dir"
cp -a "$payload/." "$new_dir/"
(cd "$new_dir" && UV_CACHE_DIR="$install_dir/cache/uv" uv sync --frozen --no-dev --python 3.12)
[[ -x "$new_dir/.venv/bin/python" ]] || die 'dependency installation failed'

# Validate migrations, diagnostics, and the real stdio protocol against disposable state.
test_db="$staging/test.db"
(cd "$new_dir" && NOESIS_DB_PATH="$test_db" .venv/bin/alembic upgrade head)
NOESIS_DB_PATH="$test_db" "$new_dir/.venv/bin/noesis" diagnose >/dev/null
NOESIS_DB_PATH="$test_db" "$new_dir/.venv/bin/python" "$new_dir/deploy/mcp-smoke.py" \
  "$new_dir/.venv/bin/python" -m noesis.mcp

# Refuse migration while any Hermes-owned Noesis process is alive.
exec 9<"$install_dir/state/runtime.lock"
flock -n 9 || die 'Noesis is active; reload/stop Hermes MCP and retry the update'
if [[ -L "$install_dir/releases/current" ]]; then previous=$(readlink "$install_dir/releases/current"); fi
if [[ -f "$install_dir/state/noesis.db" ]]; then
  had_database=1
  backup="$install_dir/backups/pre-$tag-$(date -u +%Y%m%dT%H%M%SZ).db"
  python3 - "$install_dir/state/noesis.db" "$backup" <<'PY'
import sqlite3,sys
with sqlite3.connect(sys.argv[1]) as source, sqlite3.connect(sys.argv[2]) as target:
    source.backup(target)
    if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise SystemExit("backup integrity check failed")
PY
  chmod 0600 "$backup"
  migration_test="$staging/migration-test.db"
  cp -p "$backup" "$migration_test"
  "$new_dir/.venv/bin/python" "$new_dir/deploy/prepare-legacy.py" "$migration_test"
  (cd "$new_dir" && NOESIS_DB_PATH="$migration_test" .venv/bin/alembic upgrade head)
fi

# Database restoration in the EXIT trap makes migration + code switching one recoverable operation.
migration_started=1
"$new_dir/.venv/bin/python" "$new_dir/deploy/prepare-legacy.py" "$install_dir/state/noesis.db"
(cd "$new_dir" && NOESIS_DB_PATH="$install_dir/state/noesis.db" .venv/bin/alembic upgrade head)
ln -s "$tag" "$install_dir/releases/.next-link"
mv -Tf "$install_dir/releases/.next-link" "$install_dir/releases/current"
switched=1
NOESIS_DB_PATH="$install_dir/state/noesis.db" "$new_dir/.venv/bin/noesis" diagnose >/dev/null
NOESIS_DB_PATH="$install_dir/state/noesis.db" "$new_dir/.venv/bin/python" "$new_dir/deploy/mcp-smoke.py" \
  "$new_dir/.venv/bin/python" -m noesis.mcp

for launcher in noesis-mcp noesis-admin; do
  install -m 0755 "$new_dir/deploy/$launcher" "$install_dir/bin/$launcher.next"
  mv -f "$install_dir/bin/$launcher.next" "$install_dir/bin/$launcher"
done
install -m 0755 "$new_dir/deploy/update.sh" "$install_dir/deploy/update.sh.next"
mv -f "$install_dir/deploy/update.sh.next" "$install_dir/deploy/update.sh"
printf '%s\n' "$tag" > "$install_dir/state/current-release"
switched=
printf 'Updated Noesis to %s. Reload Hermes MCP and run: hermes mcp test noesis\n' "$tag"
