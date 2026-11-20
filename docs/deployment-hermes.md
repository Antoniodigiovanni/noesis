# Install Noesis for Hermes Agent

This guide installs Noesis as a local stdio MCP server. Hermes remains the model and conversational interface; Noesis stores learning records and schedules reviews locally. The live acceptance report is tracked separately in [`acceptance-report.md`](acceptance-report.md).

## Requirements

- Python 3.12 or 3.13
- `uv`
- Hermes Agent with MCP support
- SQLite built with FTS5

## Install and initialize

```bash
git clone https://github.com/Antoniodigiovanni/noesis.git
cd noesis
uv sync --frozen --extra dev
mkdir -p "$HOME/.local/share/noesis"
NOESIS_DB_PATH="$HOME/.local/share/noesis/noesis.db" .venv/bin/noesis init-db
NOESIS_DB_PATH="$HOME/.local/share/noesis/noesis.db" .venv/bin/noesis diagnose
```

Record the checkout path. Use absolute paths in the Hermes configuration. Keep the database outside the Git checkout and back it up before upgrades.

## Configure MCP

Merge the following into the active Hermes profile's `config.yaml`. Replace both example paths. Keep tool execution sequential: several Noesis tools mutate shared SQLite state.

```yaml
mcp_servers:
  noesis:
    command: "/absolute/path/to/noesis/.venv/bin/python"
    args: ["-m", "noesis.mcp"]
    env:
      NOESIS_DB_PATH: "/absolute/path/to/noesis-data/noesis.db"
    supports_parallel_tool_calls: false
    sampling:
      enabled: false
    elicitation:
      enabled: false
    tools:
      include:
        - propose_capture
        - commit_capture
        - start_review
        - submit_attempt
        - resolve_learning_issue
        - update_learning_state
        - recall_context
        - get_progress
      resources: false
      prompts: false
```

MCP sampling is unnecessary: Hermes generates questions and assessments in the normal conversation flow. Elicitation is disabled because Noesis reviews are durable and may be answered later, not through a blocking MCP form.

## Install the Noesis skill

Copy the procedure skill into the active profile's skill directory:

```bash
mkdir -p "$HOME/.hermes/skills/productivity/noesis"
cp integrations/hermes/SKILL.md "$HOME/.hermes/skills/productivity/noesis/SKILL.md"
```

After updating the configuration and skill, start a fresh Hermes session (or use the supported MCP/skill reload commands for that installed version). Confirm that the Noesis server is connected and exactly these eight tools are available: `propose_capture`, `commit_capture`, `start_review`, `submit_attempt`, `resolve_learning_issue`, `update_learning_state`, `recall_context`, and `get_progress`.

## First-use acceptance

Use disposable study material first. Verify that:

1. Hermes only captures after an explicit request and shows a proposal before committing.
2. The database keeps source provenance and the user's uncertainty; no made-up locator is added.
3. A review asks one question without showing the answer first.
4. Hermes records the question and answer; Noesis, not Hermes, computes the next due date.
5. A review resumes after the process or conversation changes.
6. A dispute or bad question can be resolved without deleting the original attempt.
7. `recall_context` returns provenance and Hermes preserves it in its answer.

The detailed release gate and evidence fields are in [`product-spec.md`](product-spec.md) and [`acceptance-report.md`](acceptance-report.md). A unit test or raw MCP-client test is not proof of a live Hermes acceptance pass.

## Backups and maintenance

```bash
NOESIS_DB_PATH="$HOME/.local/share/noesis/noesis.db" .venv/bin/noesis diagnose
NOESIS_DB_PATH="$HOME/.local/share/noesis/noesis.db" .venv/bin/noesis export "$HOME/noesis-backup.json"
```

Protect exported data like the database: it includes study material and answer history. `noesis delete-all --confirm DELETE-NOESIS` permanently removes the configured SQLite database and its WAL files; only run it when you intentionally want to erase that data and have handled backups.

## Current limitations

Noesis currently has no standalone GUI/mobile app, direct Anki desktop/AnkiWeb synchronization, Anki package import/export, automatic Hermes memory mirroring, semantic/vector search, or OCR pipeline. It is conversational, uses a local lexical index, and depends on Hermes for language generation and assessment. Do not describe these limitations as implemented features.

## New web product / remote MCP (supersedes stdio for production)

The preceding local stdio acceptance notes are historical compatibility evidence,
not acceptance of the standalone product. Production should run the independent
`noesis-mcp-http` service described in [the native runbook](deployment-native.md).
It uses Streamable HTTP at the private-proxied `/mcp` URL (loopback origin port
8092), a protected dedicated bearer token and `NOESIS_MCP_USER_ID`. Both adapters
have eight named tools, but **their argument schemas differ**. Discover the remote
schemas rather than reusing legacy capture/assessment payloads.

The installed Python MCP 2.2.0 SDK supports `streamable_http_app`; its real
initialize/list-tools/call-tool protocol and bearer/Origin rejection are tested
in-process. That is not evidence of a reachable private route or live Hermes call.
No Hermes profile or active configuration was changed during implementation.

For the deployed Hermes version, verify its URL/transport/header-secret mechanism
before writing the final remote client configuration. Supply the dedicated bearer
through that version's supported protected secret mechanism; do not paste it into
Git or ordinary logs. Set `supports_parallel_tool_calls: false`, disable sampling
and elicitation, disable resource/prompt discovery, and allowlist exactly:
`propose_capture`, `commit_capture`, `start_review`, `submit_attempt`,
`resolve_learning_issue`, `update_learning_state`, `recall_context`, `get_progress`.
The old `config.example.yaml` is deliberately retained as a stdio-only reference.
An exact live Hermes HTTP config has not been verified, so none is claimed here.

Remote workflow:

1. With explicit user intent, Hermes selects relevant memories using its own
   access rules. Show selected text, origin/reference and proposed cards first.
2. Call `propose_capture` with a Noesis-owned `deck_id`, selected `source`, optional
   `origin`, `source_type:"hermes_memory"`, card `items` (`front`,`back`, optional
   uncertainty/explanation), and an idempotency key. Noesis retains a snapshot.
   The deck ID is visible in authenticated `/api/decks`; remote deck discovery is
   not a separate MCP tool in this version.
3. Direct the learner to **Add material** in the web UI to edit/approve/reject.
   Remote `commit_capture` only reports whether a proposal remains pending. It
   cannot claim approval, activate a draft or override the web decision.
4. `recall_context` searches approved, active web cards in the machine account's
   scope and returns provenance/uncertainty as untrusted content.
5. Web study is primary. Remote conversational review supports `start_review`,
   explicit reveal using `start_review(reveal:true, review_session_id:...)`, and
   `submit_attempt` with the learner's explicit self-grade (1–4) and exact response.
   The machine must not invent a self-grade. No AI assessment is represented as
   objective factual accuracy. Scheduler state is always computed by Noesis.
6. Remote `resolve_learning_issue` suspends a card for web inspection; it does not
   implement legacy AI assessment disputes. `update_learning_state` supports only
   active/suspended/archived. Use web settings for retention/limits and web progress
   for auditable review invalidation/rebuild.

Before release, exercise actual private-route authentication, tool discovery,
selected-memory proposal, web approval and later recall from a live Hermes session.
Keep the memory store separate. Provider access is independent from memory access;
Hermes going offline must not interrupt the Noesis web app.
