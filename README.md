# Noesis

Noesis is a local-first deterministic learning substrate for Hermes Agent. Hermes performs language reasoning; Noesis owns durable provenance, review evidence, policy, retrieval, and FSRS scheduling.

Noesis contains no model provider integration and requires no model credential.

## Local development

Requires Python 3.12 or 3.13, `uv`, and SQLite with FTS5.

```bash
UV_CACHE_DIR=/tmp/noesis-uv-cache uv sync --extra dev
.venv/bin/pytest
NOESIS_DB_PATH="$PWD/noesis.db" .venv/bin/noesis init-db
NOESIS_DB_PATH="$PWD/noesis.db" .venv/bin/noesis diagnose
```

Run the stdio MCP server:

```bash
NOESIS_DB_PATH="$PWD/noesis.db" .venv/bin/python -m noesis.mcp
```

## Hermes deployment

Development happens in this repository. Install the completed package and run live acceptance testing on the target Hermes machine. See [the deployment guide](docs/deployment-hermes.md) and copy the example in `integrations/hermes/config.example.yaml` into the target profile's `~/.hermes/config.yaml`.

## Administrative commands

```bash
noesis diagnose
noesis export backup.json
noesis delete-all --confirm DELETE-NOESIS
```

`delete-all` physically deletes the configured SQLite database and its WAL files. It is not recoverable unless an external backup exists.

