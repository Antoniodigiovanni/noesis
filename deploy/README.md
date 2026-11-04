# Native Hermes deployment

Noesis adapts Marketmind's native release pattern without copying its HTTP
service model. Releases and locked environments are immutable and versioned;
the `current` symlink switches atomically; SQLite state and backups live outside
releases. Noesis remains a **stdio MCP server**, so Hermes—not systemd—must spawn
and own the process. There is no Noesis service, container, or network port.

## Layout and requirements

The default layout is:

```text
/srv/noesis/
  bin/noesis-mcp       # stable Hermes launcher
  bin/noesis-admin     # stable administrative launcher
  deploy/update.sh
  releases/vX.Y.Z/
  releases/current -> vX.Y.Z
  state/noesis.db      # private mutable data
  cache/
  backups/
```

Run installation and updates **as the account that runs Hermes**, even when the
operator uses a different administrative account. The host needs Bash 4+,
Python 3, `uv`, `flock`, `curl`, `tar`, and `sha256sum`. An administrator uses
`sudo` only to create `/srv/noesis` with the Hermes account as owner. Mutable
directories are mode `0700`; launchers enforce `umask 077`. Never run the
installer or updater as root, and do not make private state readable by the
operator account merely to simplify deployment.

## First installation

> **Important:** the installer does not discover, infer, or prompt for the
> Hermes account. Before running it, identify the account whose home contains
> the active Hermes profile (normally `~/.hermes/config.yaml`), confirm it with
> the target operator, and switch to that account. A `.hermes` directory under
> `/home` is only a clue and must not be treated as authoritative.

First, from the administrative account, create the application root for the
confirmed Hermes account (replace both placeholders):

```bash
HERMES_USER=hermes
HERMES_GROUP=hermes
sudo install -d -m 0755 -o "$HERMES_USER" -g "$HERMES_GROUP" /srv/noesis
sudo -iu "$HERMES_USER"
```

In that Hermes-account shell, download both release assets (or transfer them to
a location readable by this account), verify the checksum, and extract only to
obtain the bootstrap installer:

```bash
release=vX.Y.Z
base="https://github.com/Antoniodigiovanni/noesis/releases/download/$release"
curl -fLO "$base/noesis-$release-native.tar.gz"
curl -fLO "$base/noesis-$release-native.tar.gz.sha256"
sha256sum -c "noesis-$release-native.tar.gz.sha256"
mkdir bootstrap && tar -xzf "noesis-$release-native.tar.gz" -C bootstrap
bootstrap/noesis/deploy/install.sh "$PWD/noesis-$release-native.tar.gz"
/srv/noesis/deploy/install-hermes-skill.sh
```

The skill installer copies the audited bundled skill into the current account's
`~/.hermes/skills/productivity/noesis/SKILL.md`; it never writes another user's
home. Rerun it after each Noesis update, then inspect the diff if the local skill
was customized.

The updater independently verifies the checksum and rejects archives containing
absolute paths, traversal, links, devices, duplicate members, or an unexpected
root. It checks the release manifest, package version, and lock-file digest;
creates the frozen Python 3.12 environment; applies Alembic migrations; and
performs diagnostics plus a real MCP initialize/list-tools exchange.

Configure Hermes with the stable launcher:

```yaml
mcp_servers:
  noesis:
    command: "/srv/noesis/bin/noesis-mcp"
    args: []
    supports_parallel_tool_calls: false
    sampling:
      enabled: false
    elicitation:
      enabled: false
```

Retain the tool allowlist from `integrations/hermes/config.example.yaml`. Install
the Noesis Hermes skill as described in `docs/deployment-hermes.md`, then run:

```bash
hermes mcp test noesis
/srv/noesis/bin/noesis-admin diagnose
```

Verify exactly eight tools before using production data.

## Updating and rolling back

A running stdio child keeps a shared runtime lock. Before updating, reload or
stop Noesis in Hermes so no MCP child remains. Run the updater as the Hermes
account (`sudo -iu <hermes-user>` from an administrative shell), then run:

```bash
/srv/noesis/deploy/update.sh vX.Y.Z
# For a private repository, transfer both files and pass the archive path:
/srv/noesis/deploy/update.sh /path/to/noesis-vX.Y.Z-native.tar.gz
/srv/noesis/deploy/install-hermes-skill.sh
```

The updater refuses to migrate while a child is active. It creates a consistent
SQLite backup, tests the migration on a copy, migrates live state, switches the
release, and validates the protocol. If validation fails, it restores both the
previous symlink and the pre-update database. After success, reload Hermes MCP
and rerun `hermes mcp test noesis`; the updater cannot reload Hermes itself.

Checksums detect transfer corruption but do not authenticate a compromised
GitHub release. Use repository protections and verify release provenance in
higher-assurance environments. Retain off-host encrypted backups and test
restores. The local pre-update copies are rollback aids, not a backup strategy.
