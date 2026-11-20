# Native homelab release runbook

Status: artifacts and local automated checks exist. A **user-level preview** is now
running as `noesis-web.service` and `noesis-mcp.service` under the existing Hermes
user manager. It uses only `/home/hermes/.local/share/noesis-preview/noesis.db`
(mode 0600, parent 0700), binds to `127.0.0.1:8091` and `:8092`, and is not the
PostgreSQL production release. The existing `noesis.antovanni.com` Caddy site is
behind the shared Cloudflare Access JWT gate; unauthenticated public requests receive
an Access login redirect. The preview database is separate from the default Noesis
legacy DB. PostgreSQL runtime/restore, production user/service lifecycle, actual
Access-authenticated browser rendering and real Hermes profile integration remain
unaccepted. Never promote this preview as production.

## Provisioning boundaries

Use a dedicated `noesis` Unix account without an interactive login, a dedicated
PostgreSQL database and role, and the existing private authenticated proxy. A DB
administrator must provision the role/database separately. The application role
must have no superuser, role creation or database creation rights and no access to
other application databases. Grant only connect and schema/table/sequence rights
inside its own DB (migration ownership inside that DB is required). PostgreSQL must
remain loopback/private; do not alter shared PostgreSQL listen/auth settings here.

Noesis does not inspect or change Marketmind, Hermes, DNS, reverse proxies or
other hosts. Operators must verify those systems separately. No deployment script
creates a database or modifies shared PostgreSQL configuration.

## Files and secrets

- `/opt/noesis/releases/VERSION`: root-owned immutable release, readable by noesis.
- `/opt/noesis/current`: active version symlink; `/opt/noesis/previous`: prior version.
- `/etc/noesis/noesis.env`: root:noesis 0640, based on `deploy/noesis.env.example`.
- `/etc/noesis/provider-key`, `/etc/noesis/mcp-token`: noesis-readable, mode 0600
  (or root:noesis 0640). Use a random dedicated MCP token of at least 32 characters.
- `/etc/noesis/pg_service.conf` and a 0600 libpq password file: separate production
  and isolated restore-test services. These are used by pg_dump/pg_restore, not the
  SQLAlchemy driver. Configure the same dedicated production DB in both places.
- `/var/lib/noesis`: noesis-owned 0750 durable files/backups, outside releases.

Supply secrets through these protected files; never command-line passwords,
browser settings, Git, ordinary logs or exports. The env example is compatible
with systemd and trusted shell sourcing by the operator scripts. Do not put shell
expressions in it. Ensure its values are correctly quoted for both parsers. The
web service uses opaque database sessions; there is no session signing key.

Production requires `NOESIS_ENV=production`, `NOESIS_DATABASE_URL` beginning
`postgresql+psycopg://`, and an HTTPS `NOESIS_ORIGIN`. Production refuses SQLite.
Local dev/test retains explicit `NOESIS_DB_PATH`. The psycopg pure Python driver
requires system libpq. A PostgreSQL endpoint and real credentials were not accessed
in implementation. Runtime PostgreSQL acceptance remains blocked pending staging.

## Optional single-user Cloudflare Access sign-in

Code support is opt-in. The user-level preview enables it with
`NOESIS_ACCESS_ENABLED=true`; no `NOESIS_ACCESS_EMAIL` is configured. Set the flag
in protected service configuration to enable it on other installations. The existing
verifier's validated human email
is accepted and mapped to `NOESIS_ACCESS_OWNER=owner` by default, an existing
account. Retain its password for local fallback only. Optionally configure one
exact `NOESIS_ACCESS_EMAIL` for defense in depth; invalid nonempty values refuse
startup. **Expanding Cloudflare Access policy shares owner data with every admitted
human. The verifier audience may cover a wildcard application spanning multiple
hostnames; check its scope and policy accordingly.** Keep
`NOESIS_SECURE_COOKIES=true` for an HTTPS preview and retain the exact HTTPS
`NOESIS_ORIGIN`. Enabling requires a separately authorized service restart.

The shared Caddy gate strips inbound `X-Hermes-Verified-Email` and forward-auths
against the existing loopback verifier. Noesis nevertheless verifies each API JWT
itself through fixed `http://127.0.0.1:8790/verify`, since local processes can call
8091 directly. Caddy must preserve `Cf-Access-Jwt-Assertion` to Noesis. The verifier
must return its validated email in exactly one `X-Hermes-Verified-Email` response
header and enforce the intended Access issuer/audience/signature/expiry policy.
No new proxy configuration, verifier implementation, credentials, dependencies or
DB migration are supplied. See [request authentication and fallback](web-api.md#authentication-and-requests)
for failure behavior, CSRF lifetime and logout limitations.

Tests use disposable databases and mock only the loopback verifier connection.
Live verifier compatibility with an Access-authenticated browser session remains
**unverified**. The preview web service was restarted with Access mode enabled;
Caddy/cloudflared, verifier configuration, secrets and real database data were not
changed. Static assets are read on every preview request, and the UI boot supports
automatic session discovery.

## Build and first install (operator only)

1. Run tests and inspect all changes. `deploy/release.sh VERSION OUTPUT_DIRECTORY`
   builds a tarball and checksum from this checkout (no Git commit required).
   It includes source/assets, locked dependencies, migrations, docs and service
   scripts. `uv build` independently builds a wheel and source distribution.
2. Verify the checksum. Inspect the trusted archive, then extract into
   `/opt/noesis/releases/VERSION`. Reject untrusted archives/path traversal.
3. Provision the identity, protected configuration and dedicated DB as above.
   Stage against an isolated DB first. The installer assumes `uv`, Python 3.12/3.13,
   libpq, PostgreSQL client tools and systemd are installed; Docker is not required.
   Set `NOESIS_PYTHON` to a host-installed 3.12/3.13 interpreter outside `/home` and
   `/root`, so `ProtectHome=yes` does not block it. Installation disables managed
   Python downloads and copies dependencies into the release venv.
4. From the prepared release run `deploy/lifecycle.sh install ABSOLUTE_RELEASE_DIR`
   as the host operator. It installs locked dependencies, runs migrations as the
   service identity, switches the symlink, installs/enables/restarts the two units,
   and probes loopback health. Do this only on an approved host. It does not create
   accounts or secrets. MCP will fail closed until its account/token is configured.
5. Provision an account using the release's `noesis-admin user create USERNAME`
   with protected environment loaded under the service identity; enter the password
   at the prompt. `noesis-admin user list` returns IDs for the MCP account scope.
   Configure `NOESIS_MCP_USER_ID`, then restart the intended unit explicitly.
6. Verify app authentication and CSRF at the origin, MCP bearer rejection/acceptance,
   and listeners `127.0.0.1:8091` and `127.0.0.1:8092`. Route through the existing
   private proxy/identity gate. Do not bind publicly. Both apps disable automatic
   trust of forwarded headers; `NOESIS_ORIGIN` supplies the browser origin check.
7. MCP DNS-rebinding protection accepts loopback hosts. If a private proxy preserves
   a different Host, list its exact hostname (including port when needed) in
   `NOESIS_MCP_ALLOWED_HOSTS`, comma separated. Do not disable host checking.
8. Verify desktop/mobile browser acceptance and the live Hermes memory push → web
   approval → recall workflow. Record evidence without tokens/keys.

An initial account must exist before MCP starts successfully. For first staging,
run migrations/account provisioning before starting units or expect MCP auth to
reject requests until provisioning is complete. The lifecycle health check alone
does not prove account configuration or end-to-end integration.

## Update, rollback, status and uninstall

Before upgrade, create and restore-check a backup into a separate empty DB and run
the target migration on that staging DB. Prepare a fresh version directory, then
`deploy/lifecycle.sh update ABSOLUTE_RELEASE_DIR BACKUP-RESTORE-VERIFIED`.
Configuration and database state remain outside the release. Dependency installation
or migration failure happens before symlink switching. If a later health check
fails, the script exits unsuccessfully; investigate and explicitly roll back.

`deploy/lifecycle.sh rollback SCHEMA-COMPATIBLE` switches code to `previous` and
restarts both services. It **does not downgrade the DB**. Verify old code/current
schema compatibility first. Migration 0002 refuses destructive downgrade. For an
incompatible schema, restore the pre-upgrade backup into a newly provisioned DB,
verify it there, and explicitly switch the protected DB configuration.

`deploy/lifecycle.sh status` shows systemd state, active release and health. Run
`noesis-admin diagnose` from the configured release to check DB/schema/FSRS version.
Units run without root, with a restrictive umask, filesystem protection, empty
capabilities and no-new-privileges. The provider may require outbound HTTPS; no
broad inbound firewall opening is part of installation.

Uninstall: explicitly stop/disable only `noesis-web` and `noesis-mcp`, remove their
units and reload systemd, then remove versioned releases if desired. Preserve
`/etc/noesis`, `/var/lib/noesis`, DB and verified backups until a separate explicit
retention/deletion decision. Never run a shared-service teardown.

## Backup and restore check

Load the protected libpq environment, then run:

```text
deploy/database.sh backup /secure-backups/noesis-TIMESTAMP.dump
deploy/database.sh restore-check /secure-backups/noesis-TIMESTAMP.dump noesis-restore-test noesis_restore_acceptance
```

The restore service must differ from production, point to the expected
`noesis_restore_*` database, and have an empty public schema. The script refuses
nonempty targets, restores in a transaction with exit-on-error and checks schema,
card and review counts. The isolated DB must be provisioned separately. Follow
with app/API/MCP acceptance using that isolated DB. A backup file or `pg_restore
--list` alone is not a verified recovery. Off-host encrypted backup scheduling,
retention, key management and restore drills are operator responsibilities, not
implemented automation. Back up secret/config files separately with restricted
access; database exports exclude browser credentials by default.

## Existing SQLite migration

Never point a migration command at the actual user DB without an explicit plan.
The checkout's `noesis.db` and the user's default database were not opened here.

1. Stop writers by an approved maintenance action and make an SQLite online backup
   using SQLite's backup API. Copying a live WAL database file alone is unsafe.
2. Preserve the original. Verify its backup with `PRAGMA integrity_check` and record
   counts. All development/tests here use disposable fixture DBs.
3. Provision an **empty** dedicated PostgreSQL DB, run `noesis-admin db-upgrade`
   with target configuration, then run `noesis-admin import-sqlite BACKUP_PATH
   --confirm IMPORT-INTO-EMPTY` against that target. It opens the SQLite source
   read-only, copies recognized typed tables in FK order, and refuses a nonempty
   target. Browser login sessions are deliberately not copied. IDs, revisions,
   review evidence, legacy FSRS state, account password hashes and audit records
   are preserved; FTS5 is not copied to PostgreSQL. Compare reported table counts.
4. Existing legacy units remain in legacy tables; migration does not fabricate
   web questions or silently bind `learner_id=default` to an account. The browser
   card collection is separate. Re-author legacy units as web cards/proposals
   after inspecting their source/question quality; they start a new web review
   history. Legacy history remains available via legacy exports. This is a
   material compatibility limitation, not full legacy-to-web conversion.
5. Verify scoped app operations and a PostgreSQL backup/restore into another DB
   before changing any production configuration. PostgreSQL legacy recall uses a
   portable lexical fallback over current knowledge-unit statements, rather than
   FTS5 ranking/concept/source matching. Advanced PostgreSQL search is deferred.

The transfer logic is tested SQLite→SQLite with disposable data; PostgreSQL DDL
compiles and both migration branches exist. Real SQLite→PostgreSQL import,
concurrency, backup and restore **have not run** because this sandbox denies DB
sockets. Production acceptance is blocked until those tests pass on isolated staging.
