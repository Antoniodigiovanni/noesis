"""Contracts for the host-native stdio MCP deployment."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_release_builds_a_verified_single_root_archive() -> None:
    workflow = text(".github/workflows/release.yml")
    updater = text("deploy/update.sh")
    assert "bundle/noesis" in workflow
    assert "UV_LOCK_SHA256" in workflow and "UV_LOCK_SHA256" in updater
    assert "sha256sum -c" in updater
    assert 'path.parts[0] != "noesis"' in updater
    assert "member.isfile() or member.isdir()" in updater
    assert "uv sync --frozen --no-dev" in updater


def test_update_coordinates_stdio_children_and_database_rollback() -> None:
    updater = text("deploy/update.sh")
    launcher = text("deploy/noesis-mcp")
    assert 'flock -s 9' in launcher
    assert 'flock -n 9' in updater
    assert "source.backup(target)" in updater
    assert 'PRAGMA integrity_check' in updater
    assert 'alembic upgrade head' in updater
    assert 'rm -f "$install_dir/state/noesis.db"{,-wal,-shm}' in updater
    assert 'mv -Tf "$install_dir/releases/.next-link"' in updater


def test_hermes_launches_stdio_directly_without_systemd_or_network() -> None:
    launcher = text("deploy/noesis-mcp")
    config = text("integrations/hermes/config.example.yaml")
    assert 'exec .venv/bin/python -m noesis.mcp' in launcher
    assert '/srv/noesis/bin/noesis-mcp' in config
    assert "supports_parallel_tool_calls: false" in config
    assert "enabled: false" in config
    assert not (DEPLOY / "noesis.service").exists()
    for path in ("deploy/noesis-mcp", "deploy/noesis-admin", "deploy/update.sh"):
        assert "systemctl" not in text(path)


def test_private_state_and_stable_launchers_are_outside_releases() -> None:
    updater = text("deploy/update.sh")
    assert 'install -d -m 0700 "$install_dir/state"' in updater
    assert 'chmod 0600 "$install_dir/state/runtime.lock"' in updater
    assert '"$install_dir/bin/$launcher"' in updater
    assert 'export HOME=' not in text("deploy/noesis-mcp")


@pytest.mark.parametrize(
    "script", ["install.sh", "update.sh", "noesis-mcp", "noesis-admin"]
)
def test_deployment_script_shell_syntax(script: str) -> None:
    subprocess.run(["bash", "-n", str(DEPLOY / script)], check=True)


def test_protocol_smoke_script_compiles() -> None:
    subprocess.run(
        ["python3", "-m", "py_compile", str(DEPLOY / "mcp-smoke.py")],
        check=True,
    )
