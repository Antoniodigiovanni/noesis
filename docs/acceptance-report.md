# Live Hermes acceptance report

Status: **partial** — live Hermes MCP connection/discovery was verified in an isolated scratch profile, but the end-to-end conversational acceptance workflow has not been run against the user's active profile. Do not treat tool discovery alone as production acceptance.

## Environment checks completed

- Hermes executable: `/home/hermes/.local/bin/hermes`
- Hermes version: `0.21.4` (`2026.9.21`, upstream commit `32eeacdf`), verified with `hermes --version`.
- `hermes mcp test noesis` passed using an isolated `HERMES_HOME` scratch profile: stdio connected and Hermes discovered exactly eight tools. The user's active/default profile was not changed.
- `uv sync --frozen --extra dev` succeeded in the repository and created a Python 3.12.14 virtual environment.
- Automated command: `.venv/bin/python -m pytest -o 'addopts=' -q`.
- Current result after the continuation fixes: **30 passed**, with two Typer/Click deprecation warnings. The earlier 17- and 27-test counts are historical.
- `uv lock --check` passed. A fresh offline build produced exactly one wheel and one source distribution under the scratch directory.
- Post-fix disposable Chromium acceptance passed at desktop and mobile widths: login, hidden/revealed answer, persisted grade, restart/resume, and 390px overflow check. No screenshot-based visual or full accessibility audit is claimed.
- An isolated Hermes profile connected to the local authenticated Streamable HTTP endpoint and discovered exactly eight tools. A fresh synthetic fixture proposal remained inactive, was approved only through the separate Noesis service lane, and was returned by MCP recall. No real personal-memory workflow or private-proxy acceptance is claimed.
- PostgreSQL DDL compiled, but PostgreSQL runtime/restore remains unverified; the project venv has no psycopg and PyPI DNS failed during implementation. No production host/profile/data was changed.
- Noesis package version is `0.1.0`; the standalone web schema is migration `0002` (separate from the retained legacy schema); FSRS is pinned to `6.3.2`.
- SQLite FTS5 is available in the installed environment; the MCP subprocess/restart tests use a disposable database.

## Required live workflow evidence

- [ ] Add Noesis MCP to the intended Hermes profile with sequential calls, sampling disabled, elicitation disabled, and only eight allowlisted tools.
- [ ] Start a fresh Hermes conversation and confirm exactly eight Noesis tools are discovered.
- [ ] Explicitly request capture; verify narrow proposed units and preserved user/source uncertainty.
- [ ] Approve at least two units and edit or reject another; inspect provenance and event records.
- [ ] Make a unit due using only a disposable acceptance database.
- [ ] Start a review; verify the question is shown before the answer and the session is durable.
- [ ] Submit a partial/difficult answer; verify Noesis calculates FSRS state.
- [ ] Dispute a grade; verify original assessment remains and resolution is append-only.
- [ ] Mark an ambiguous question and verify it can be invalidated without deleting history.
- [ ] Change importance; verify memory strength is unchanged.
- [ ] Suspend/resume a unit.
- [ ] Restart Noesis and resume an unfinished review.
- [ ] Recall learned context in ordinary Hermes work with provenance intact.
- [ ] Back up/export test data and verify destructive deletion only on a disposable database.

## Optional paths

- Obsidian: not run; use an identified disposable note and record availability/blocker.
- OCR/vision: not run; use a fixture or disposable image and record availability/blocker.

## Operator note

A diagnostic run without `NOESIS_DB_PATH` initialized or opened the default database at `/home/hermes/.local/share/noesis/noesis.db`. It was not deleted or modified further. Use an explicit disposable path for future acceptance testing and inspect this default database before relying on it.

## Standalone web-product implementation update (2026-10-26)

The historical Hermes discovery result above remains historical; it was not rerun
against an active profile. New local evidence, test commands, transport coverage,
packaging checks and explicit sandbox blockers are recorded in
[implementation-report.md](implementation-report.md). Synthetic fixture MCP proposal→approval→recall passed; the configured hostname returns the Cloudflare Access login redirect and local Caddy denies origin requests without a JWT. No authenticated Access browser session, real personal-memory workflow or production deployment is claimed.
