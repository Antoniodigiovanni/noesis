# Deploy to the Hermes machine

The configuration below is based on official Hermes Agent 0.21.1 source at commit `b1f003e18633298d549668b8e186af84cca45b76`. Confirm the actual target version before installation and record it in `docs/acceptance-report.md`.

## Inspect the target

```bash
command -v hermes
hermes --version
hermes mcp --help
hermes skills --help
hermes cron --help
python3 --version
```

Also inspect the active profile and `~/.hermes/config.yaml`. Do not modify Hermes core.

## Install Noesis

From a release checkout on the Hermes machine:

```bash
uv venv --python 3.12 .venv
UV_CACHE_DIR=/tmp/noesis-uv-cache uv sync --frozen
mkdir -p ~/.local/share/noesis
NOESIS_DB_PATH="$HOME/.local/share/noesis/noesis.db" .venv/bin/noesis init-db
```

Merge `integrations/hermes/config.example.yaml` into the active Hermes profile configuration after replacing both absolute paths. Sampling, elicitation, resource wrappers, prompt wrappers, and parallel calls must remain disabled.

Install the skill:

```bash
mkdir -p ~/.hermes/skills/productivity/noesis
cp integrations/hermes/SKILL.md ~/.hermes/skills/productivity/noesis/SKILL.md
hermes skills list
hermes mcp test noesis
```

Start a fresh session or run `/reload-mcp`. Verify exactly eight tools named `mcp__noesis__<tool-name>`.

## Scheduled review

Create the job from a normal Hermes conversation so `deliver: origin` captures the intended conversation. Attach the `noesis` skill and set `attach_to_session: true`. The prompt must be self-contained: call `get_progress`, call `start_review` only if eligible work exists, produce one question following the skill, and return `[SILENT]` when nothing is due.

Run it once immediately with `hermes cron run <job-id>` and reply on the continuable delivery surface before enabling the recurring schedule.

For acceptance step 8 only, a unit can be made due with the guarded fixture below. It refuses to run unless the opt-in variable is present and should never be added to the Hermes MCP environment:

```bash
NOESIS_ENABLE_TEST_FIXTURES=1 .venv/bin/noesis test-make-due <knowledge-unit-id>
```
