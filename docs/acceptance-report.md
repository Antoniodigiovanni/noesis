# Live Hermes acceptance report

Status: **not run** — Hermes is not installed on the development workstation. This report must be completed on the deployment machine; mocked results must not be recorded as live evidence.

Local inspection on 2026-09-09:

- `command -v hermes`, `command -v hermes-agent`, and `command -v hermes-cli` returned no installation.
- System Python: `3.14.6`; Noesis environment: CPython `3.12.13` created by `uv 0.11.3`.
- SQLite FTS5 is available.
- Official Hermes source inspected at commit `b1f003e18633298d549668b8e186af84cca45b76`, version `0.21.1`, dated 2026-09-08.
- Relevant current source was inspected under `website/docs/reference/mcp-config-reference.md`, `website/docs/developer-guide/creating-skills.md`, `website/docs/user-guide/features/cron.md`, and `cron/scheduler_delivery.py`.

Local automated status: `17 passed` with a real stdio MCP subprocess/restart test. Alembic reports `No new upgrade operations detected`. Release wheel and source distribution build successfully. These are not substitutes for the live Hermes test.

## Environment

- Hermes path:
- Hermes version:
- Hermes commit/build:
- Python path/version:
- Noesis version:
- Commands used:

## Required workflow evidence

- [ ] Fresh Hermes conversation discovers exactly eight Noesis tools.
- [ ] *Meditations* notes produce narrow proposed units.
- [ ] User uncertainty remains distinct from source claims; no passage reference is invented.
- [ ] At least two units approved and one edited or rejected.
- [ ] Database provenance and audit events inspected.
- [ ] A test-only fixture makes one unit due.
- [ ] Durable review session created and one partial/difficult answer submitted.
- [ ] Noesis calculates the scheduler transition.
- [ ] Grade dispute preserves the original assessment and is resolved append-only.
- [ ] Ambiguous question invalidates evidence and rebuilds scheduler state without deletion.
- [ ] Importance changes while memory strength remains byte-for-byte unchanged.
- [ ] Suspension and resumption pass.
- [ ] Noesis process restarted and unfinished review resumed.
- [ ] Ordinary conversation recalls relevant learned material with provenance.

## Optional paths

- Obsidian: not run; record availability or exact blocker.
- OCR/vision: not run; record availability or exact blocker.
