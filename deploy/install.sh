#!/usr/bin/env bash
set -euo pipefail

archive=${1:-}
install_dir=${NOESIS_INSTALL_DIR:-/srv/noesis}
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

printf 'Noesis must be installed as the account that runs Hermes.\n' >&2
printf 'Current account: %s. This installer does not discover or select the Hermes account.\n' "$(id -un)" >&2

[[ $(id -u) -ne 0 ]] || { printf 'Run as the unprivileged Hermes account, not root.\n' >&2; exit 1; }
[[ -n "$archive" ]] || { printf 'usage: %s /path/to/noesis-vX.Y.Z-native.tar.gz\n' "$0" >&2; exit 2; }
[[ -f "$archive" && -f "$archive.sha256" ]] || { printf 'Archive and matching .sha256 are required.\n' >&2; exit 1; }
for command in install uv flock; do
  command -v "$command" >/dev/null || { printf 'Required command not found: %s\n' "$command" >&2; exit 1; }
done

if [[ ! -e "$install_dir" ]]; then
  command -v sudo >/dev/null || {
    printf 'Create %s as root, owned by %s, then rerun as that account.\n' "$install_dir" "$(id -un)" >&2
    exit 1
  }
  sudo install -d -m 0755 -o "$(id -un)" -g "$(id -gn)" "$install_dir"
fi
[[ -d "$install_dir" && -O "$install_dir" && -w "$install_dir" ]] || {
  printf '%s must be owned and writable by the Hermes runtime account (%s).\n' "$install_dir" "$(id -un)" >&2
  exit 1
}
install -d -m 0755 "$install_dir/deploy"
install -m 0755 "$script_dir/update.sh" "$install_dir/deploy/update.sh"
NOESIS_INSTALL_DIR="$install_dir" "$install_dir/deploy/update.sh" "$archive"

printf '\nConfigure Hermes command as: %s/bin/noesis-mcp\n' "$install_dir"
printf 'Then reload MCP and run: hermes mcp test noesis\n'
