# Noesis

Noesis is an authenticated flashcard web app for a private homelab. Capture notes,
review AI-generated drafts, and study with answer reveal and Again/Hard/Good/Easy
self-grades scheduled by pinned FSRS. The responsive warm-dark UI includes Today,
decks/cards, proposal approval, progress, settings and account security.

Hermes is optional: the authenticated Streamable HTTP MCP adapter accepts selected
memory snapshots as inactive proposals and retrieves approved Noesis cards. Noesis
never reads Hermes's private memory store. Generated cards require approval in the
web UI; a machine credential cannot approve them.

## Run locally

Requires Python 3.12/3.13 and `uv`. SQLite is supported for local development/tests;
production requires a dedicated PostgreSQL database/role and system libpq.

```bash
uv sync --frozen --extra dev
NOESIS_DB_PATH="$PWD/.dev-noesis.db" .venv/bin/python -m noesis.cli.admin user create learner
NOESIS_DB_PATH="$PWD/.dev-noesis.db" .venv/bin/python -m noesis.web.app
```

Open `http://127.0.0.1:8091`. Account creation prompts for a password of at least
14 characters. Local HTTP uses a development cookie; production requires HTTPS,
Secure cookies and an exact configured origin. Never expose the development server
publicly. No frontend package installation or asset build server is needed.

For optional generation, configure `NOESIS_PROVIDER_URL` (OpenAI-compatible base
URL such as an operator-verified `/v1` endpoint), `NOESIS_PROVIDER_MODEL`, and
`NOESIS_PROVIDER_KEY_FILE` (protected server-side file). The UI shows the configured
endpoint/model and requires consent before notes are sent. Provider failures do
not prevent browsing, manual cards or existing reviews. No real provider was
contacted during implementation.

## Readiness

The web product, scoped API, remote MCP, migrations, release artifacts and operator
runbooks are implemented and locally tested. **This is not a production-accepted
release.** Isolated PostgreSQL runtime/migration/restore and production host lifecycle
remain open. The disposable desktop/mobile browser flow passed locally; authenticated
Hermes discovery and a synthetic proposal→approval→recall round trip passed in an
isolated profile. These do not validate a real personal-memory workflow. See the
[implementation evidence and gaps](docs/implementation-report.md).

The host now has a **user-level preview** running behind the existing
Cloudflare Access gate: web `127.0.0.1:8091`, local bearer-protected MCP
`127.0.0.1:8092`, and isolated SQLite at
`/home/hermes/.local/share/noesis-preview/noesis.db`. This is a trial on the
uncommitted checkout, **not a production deployment**; production still requires
verified PostgreSQL migrations/restore and the versioned release gates in the
[runbook](docs/deployment-native.md).

The user-level preview now enables single-user Access sign-in: each API request's
JWT is independently verified by the local Access verifier and mapped to the existing
`owner` account. No duplicate email allowlist is configured; the Cloudflare Access
policy must remain single-user, or everyone admitted will share that account. The
password login remains a local fallback. See the
[configuration and trust assumptions](docs/deployment-native.md#optional-single-user-cloudflare-access-sign-in).
The initial `owner` password is stored locally at
`/home/hermes/.config/noesis/initial-login.txt` with mode 0600. Read it on the host,
change it in Noesis Settings after signing in, and remove the file. The MCP token
is separate, stored in another protected local file, and was not added to the active
Hermes profile. Public browser acceptance stops at the Access login page; the user's
own Access code is required to continue.

The [product specification](docs/product-spec.md) remains the target, not a claim
that every requirement is complete. Legacy SQLite learning tables coexist with the
new app tables; they are not automatically converted into web cards. See the
[explicit SQLite transfer strategy](docs/deployment-native.md#existing-sqlite-migration).

## Interfaces and deployment

- [Web/API contract, review and deletion semantics](docs/web-api.md)
- [Native versioned release, systemd, backup/restore and migration runbook](docs/deployment-native.md)
- [Hermes integration guide](docs/deployment-hermes.md)
- [Architecture](docs/architecture.md)

Production entry points are `noesis-web`, `noesis-mcp-http`, and `noesis-admin`.
Equivalent `python -m noesis.web.app`, `python -m noesis.mcp.http`, and
`python -m noesis.cli.admin` invocations work from the installed release. The
remote adapter binds `127.0.0.1:8092`, uses a separate protected bearer token file,
and scopes every call to the configured account ID. It exposes eight named tools;
its schema differs from the local legacy tools. Browser sessions are not MCP tokens.

```text
noesis-admin db-upgrade
noesis-admin diagnose
noesis-admin user list
noesis-admin user create USERNAME
noesis-admin user disable USERNAME
noesis-admin import-sqlite BACKUP_PATH --confirm IMPORT-INTO-EMPTY
deploy/release.sh VERSION OUTPUT_DIRECTORY
deploy/lifecycle.sh install|update|rollback|status ...
deploy/database.sh backup|restore-check ...
```

Read the runbook before operator commands. None were run against a host or actual
user database. Production SQLite is refused; no credentials or shared service
configuration are discovered automatically. Off-host backup scheduling is not
implemented. Card deletion retains history/tombstones and is not privacy erasure.

## Tests

```bash
.venv/bin/python -m pytest -q
uv lock --check
uv build
node --check src/noesis/web/static/app.js
bash -n deploy/*.sh
# Opt-in disposable loopback browser acceptance, with Chromium installed:
NOESIS_CHROMIUM=/path/to/chromium .venv/bin/python tests/browser/run.py
```

In restricted runners that deny event-loop wakeup socketpairs, use
`NOESIS_SANDBOX_TEST=1 PYTHONPATH=tests/sandbox .venv/bin/python -m pytest -q`.
This enables a test-only selector polling workaround, including stdio subprocesses.
Browser and PostgreSQL runtime checks still require a socket-capable environment.

## Local legacy compatibility

The original learning/assessment service and eight-tool stdio adapter remain for
trusted local development and compatibility tests:

```bash
NOESIS_DB_PATH="/explicit/disposable-or-backed-up/path.db" .venv/bin/python -m noesis.mcp
```

`integrations/hermes/config.example.yaml` is the legacy **stdio** example, not the
production remote setup. Its agent-supplied approval/assessment semantics are not
the new web approval boundary. Do not expose it as an authenticated remote service.
The legacy `noesis diagnose`, `noesis export PATH`, and `noesis delete-all` commands
remain. Legacy exports exclude account/session tables; authenticated `/api/export`
exports only the current account's app records. `delete-all` is destructive SQLite
maintenance and requires explicit confirmation; it is not the PostgreSQL deletion
procedure or an account privacy-purge implementation.
