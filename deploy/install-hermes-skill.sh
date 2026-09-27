#!/usr/bin/env bash
set -euo pipefail
umask 077

install_dir=${NOESIS_INSTALL_DIR:-/srv/noesis}
source_file="$install_dir/releases/current/integrations/hermes/SKILL.md"
target_dir=${HERMES_SKILL_DIR:-$HOME/.hermes/skills/productivity/noesis}

[[ $(id -u) -ne 0 ]] || {
  printf 'Run as the Hermes runtime account, not root.\n' >&2
  exit 1
}
[[ -f "$source_file" ]] || {
  printf 'Bundled Noesis skill not found: %s\n' "$source_file" >&2
  exit 1
}
install -d -m 0755 "$target_dir"
temporary=$(mktemp "$target_dir/.SKILL.md.XXXXXX")
trap 'rm -f "$temporary"' EXIT
install -m 0644 "$source_file" "$temporary"
mv -f "$temporary" "$target_dir/SKILL.md"
trap - EXIT
printf 'Installed Noesis skill for %s at %s\n' "$(id -un)" "$target_dir/SKILL.md"
printf 'Run hermes skills list, then reload MCP.\n'
