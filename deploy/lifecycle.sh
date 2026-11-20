#!/bin/bash
# Operator-invoked only. No shared PostgreSQL/proxy/Hermes configuration changes.
set -euo pipefail
umask 077
root=${NOESIS_RELEASE_ROOT:-/opt/noesis}
config=${NOESIS_CONFIG_FILE:-/etc/noesis/noesis.env}
action=${1:?usage: lifecycle.sh install|update|rollback|status ...}
load_config() {
  [[ -r "$config" ]] || { echo 'Protected configuration file required' >&2; exit 1; }
  set -a
  # shellcheck disable=SC1090
  source "$config"
  set +a
  [[ "${NOESIS_DATABASE_URL:-}" == postgresql+psycopg://* ]] || { echo 'Production requires PostgreSQL' >&2; exit 1; }
}
health() {
  curl --fail --silent --max-time 10 "http://127.0.0.1:${NOESIS_WEB_PORT:-8091}/health"
  curl --fail --silent --max-time 10 "http://127.0.0.1:${NOESIS_MCP_PORT:-8092}/health"
}
case "$action" in
install|update)
  [[ "$EUID" == 0 ]] || { echo 'Run as the host operator/root' >&2; exit 1; }
  release=${2:?absolute prepared version directory required}
  [[ "$release" == "$root/releases/"* && -f "$release/RELEASE" && -f "$release/uv.lock" ]] || exit 2
  [[ "$action" != update || "${3:-}" == BACKUP-RESTORE-VERIFIED ]] || { echo 'Verify a backup restore before update; then pass BACKUP-RESTORE-VERIFIED' >&2; exit 1; }
  id noesis >/dev/null || { echo 'Provision the dedicated noesis account first' >&2; exit 1; }
  load_config
  [[ ! -e "$release/.venv" ]] || { echo 'Use a fresh version directory' >&2; exit 1; }
  python_runtime=${NOESIS_PYTHON:-/usr/bin/python3.12}
  [[ -x "$python_runtime" && "$python_runtime" != /home/* && "$python_runtime" != /root/* ]] || { echo 'Set NOESIS_PYTHON to a system Python 3.12/3.13 outside protected home directories' >&2; exit 1; }
  (cd "$release" && UV_LINK_MODE=copy uv sync --python "$python_runtime" --no-managed-python --frozen --no-dev --no-editable)
  chown -R root:noesis "$release"
  chmod -R g+rX,go-w,o-rwx "$release"
  install -d -m 0750 -o noesis -g noesis /var/lib/noesis
  (cd "$release" && runuser -u noesis -- .venv/bin/python -m noesis.cli.admin db-upgrade)
  previous=$(readlink -f "$root/current" || true)
  [[ -z "$previous" ]] || ln -sfn "$previous" "$root/previous"
  ln -s "$release" "$root/.next"
  mv -Tf "$root/.next" "$root/current"
  install -m 0644 "$release/deploy/noesis-web.service" "$release/deploy/noesis-mcp.service" /etc/systemd/system/
  systemctl daemon-reload
  systemctl enable noesis-web noesis-mcp
  systemctl restart noesis-web noesis-mcp
  sleep 2
  health
  ;;
rollback)
  [[ "$EUID" == 0 ]] || exit 1
  [[ "${2:-}" == SCHEMA-COMPATIBLE ]] || { echo 'Confirm prior code supports current schema; no database downgrade is performed' >&2; exit 1; }
  prior=$(readlink -f "$root/previous")
  [[ "$prior" == "$root/releases/"* && -f "$prior/RELEASE" ]] || exit 1
  ln -s "$prior" "$root/.next"
  mv -Tf "$root/.next" "$root/current"
  systemctl restart noesis-web noesis-mcp
  load_config
  sleep 2
  health
  ;;
status)
  systemctl --no-pager status noesis-web noesis-mcp
  readlink -f "$root/current"
  load_config
  health
  ;;
*) echo 'Unknown action' >&2; exit 2 ;;
esac
