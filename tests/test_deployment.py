"""Contracts for the host-native stdio MCP deployment."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from noesis.persistence.models import Base

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


def test_installer_announces_that_runtime_account_selection_is_manual() -> None:
    result = subprocess.run(
        [str(DEPLOY / "install.sh")], text=True, capture_output=True
    )
    assert result.returncode == 2
    assert result.stderr.startswith(
        "Noesis must be installed as the account that runs Hermes.\n"
    )
    assert "does not discover or select the Hermes account" in result.stderr


@pytest.mark.parametrize(
    "script", ["install.sh", "update.sh", "noesis-mcp", "noesis-admin", "install-hermes-skill.sh"]
)
def test_deployment_script_shell_syntax(script: str) -> None:
    subprocess.run(["bash", "-n", str(DEPLOY / script)], check=True)


def test_skill_installer_targets_the_runtime_accounts_home(tmp_path) -> None:
    install_dir = tmp_path / "install"
    source = install_dir / "releases" / "current" / "integrations" / "hermes"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# Audited Noesis skill\n", encoding="utf-8")
    home = tmp_path / "hermes-home"
    home.mkdir()
    subprocess.run(
        [str(DEPLOY / "install-hermes-skill.sh")],
        env={
            "HOME": str(home),
            "NOESIS_INSTALL_DIR": str(install_dir),
            "PATH": os.environ["PATH"],
        },
        check=True,
    )
    installed = home / ".hermes" / "skills" / "productivity" / "noesis" / "SKILL.md"
    assert installed.read_text(encoding="utf-8") == "# Audited Noesis skill\n"


def test_protocol_smoke_and_legacy_scripts_compile() -> None:
    subprocess.run(
        [
            "python3",
            "-m",
            "py_compile",
            str(DEPLOY / "mcp-smoke.py"),
            str(DEPLOY / "prepare-legacy.py"),
        ],
        check=True,
    )


def test_prepare_legacy_stamps_only_the_exact_initial_schema(tmp_path) -> None:
    database = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        Base.metadata.create_all(connection)
        connection.exec_driver_sql("PRAGMA user_version=1")
    engine.dispose()
    subprocess.run(
        [sys.executable, str(DEPLOY / "prepare-legacy.py"), str(database)],
        check=True,
    )
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0001",)


def test_prepare_legacy_rejects_a_partial_schema(tmp_path) -> None:
    database = tmp_path / "partial.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE knowledge_units (id TEXT PRIMARY KEY)")
        connection.execute("PRAGMA user_version=1")
    result = subprocess.run(
        [sys.executable, str(DEPLOY / "prepare-legacy.py"), str(database)],
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE name = 'alembic_version'"
        ).fetchone() == (0,)
