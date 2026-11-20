#!/bin/bash
# Build from the current reviewed checkout, including uncommitted implementation.
set -euo pipefail
umask 077
version=${1:?usage: release.sh VERSION OUTPUT_DIRECTORY}
out=${2:?output directory required}
[[ "$version" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]*$ ]] || exit 2
repo=$(cd "$(dirname "$0")/.." && pwd)
mkdir -p "$out"
out=$(cd "$out" && pwd)
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
mkdir "$stage/noesis-$version"
cp -R "$repo/src" "$repo/migrations" "$repo/deploy" "$repo/docs" "$stage/noesis-$version/"
cp "$repo/pyproject.toml" "$repo/uv.lock" "$repo/alembic.ini" "$repo/README.md" "$stage/noesis-$version/"
find "$stage" -name __pycache__ -type d -exec rm -rf {} +
printf '%s\n' "$version" > "$stage/noesis-$version/RELEASE"
tar -C "$stage" -czf "$out/noesis-$version.tar.gz" "noesis-$version"
(cd "$out" && sha256sum "noesis-$version.tar.gz" > "noesis-$version.tar.gz.sha256")
printf 'Release artifact: %s/noesis-%s.tar.gz\n' "$out" "$version"
