# Noesis — Product and Release Specification

**Status:** target product definition. The repository now has a substantial, locally runnable standalone web/MCP implementation; production readiness remains gated on isolated PostgreSQL, homelab deployment, and private-route acceptance. See the dated implementation addendum and implementation report for the verified scope and open gaps.

## 1. Product

Noesis is an independent, AI-powered, Anki-style learning application for the user's homelab. It has its own authenticated web UI, API, database, review history, and release lifecycle. It is connected to Hermes Agent through MCP so selected Hermes memories can become study material and Noesis learning records can be recalled by Hermes.

Noesis is independent of Hermes at the data and service boundary, not disconnected from it:

- Noesis works as a web app even while Hermes is offline.
- Hermes remains an optional but first-class AI and memory integration.
- Hermes's private memory store and Noesis's learning database remain separate.
- The user can browse, edit, study, export, and manage Noesis material in Noesis without using a chat session.

The central learning loop is:

1. **Capture:** Add notes/material in the web UI or explicitly ask Hermes to find selected relevant memories and propose study material.
2. **Generate:** Noesis uses a configured AI provider to propose focused cards and supporting rubric/provenance from the supplied material. Hermes can also propose material through MCP.
3. **Approve:** The learner reviews, edits, rejects, or approves proposed cards. Unreviewed proposals are not active study cards.
4. **Study:** The web UI presents due cards one at a time, hides answers until reveal, records a self-grade, and shows feedback or explanations when available.
5. **Schedule:** Noesis records immutable review evidence and computes the next due date with its pinned FSRS implementation.
6. **Connect:** Hermes can retrieve relevant approved learning records from Noesis through MCP during ordinary work. Noesis does not take over or rewrite Hermes memory.

Anki is the interaction and spaced-repetition reference. Noesis should feel like a focused flashcard/study app, not merely a conversational review script. It is not an AnkiWeb clone, an Anki collection synchronizer, or a general-purpose archive.

## 2. Hermes memory boundary and MCP decision

**Recommended integration: Hermes selectively pushes memory-derived proposals into Noesis; Hermes also retrieves learning evidence from Noesis. Do not let Noesis directly read Hermes's private memory database.**

Hermes is the only component that can see its own memory store and apply its own access rules. When the user explicitly requests a memory-to-study workflow, Hermes searches or recalls its own memories, selects only the relevant content, and submits a structured proposal to Noesis over authenticated MCP. Noesis stores the submitted snapshot with source type `hermes_memory`, an origin/reference if available, and a capture timestamp. The user reviews it in the Noesis UI and approves cards before they become active.

For reverse retrieval, Hermes calls Noesis MCP tools such as `recall_context` and `get_progress`. Noesis returns only Noesis-owned learning material, with provenance and uncertainty; Hermes decides whether and how to use it. This is not a synchronization of all memories in either direction.

Rules:

- No ambient, scheduled, or full-store memory mirroring in v1.
- Never ingest private memory just because it exists. Require explicit user intent for each capture operation and visible approval before cards activate.
- The app cannot browse Hermes's filesystem, session database, or memory database.
- Record imported material as a snapshot. If Hermes later changes or forgets its original memory, retain the Noesis study record until the user explicitly updates or deletes it.
- The user can inspect, correct, unlink, archive, or delete imported material from the web UI.
- Do not send Noesis answer history back into Hermes memory automatically. Hermes may retrieve progress or a learning record in response to a relevant request.

This design gives the agent a deliberate bridge to its memory without making Noesis's availability, schema, or data integrity depend on Hermes internals.

## 3. V1 user experience

### Web UI

The authenticated web UI is the primary Noesis application and must be usable on desktop and mobile browsers. It should provide:

- **Today / Study:** due count, new-card count, a clear “Start review” action, current session progress, answer reveal, self-grade controls, and a useful completion state.
- **Decks and cards:** create and organize decks; browse/search cards; inspect front, answer, source, tags, status, and review history; edit, suspend, archive, or delete with explicit confirmation where destructive.
- **Add material:** create a source or paste/import notes; inspect an AI-generated proposal; edit/reject/approve cards before activation; identify duplicates and source uncertainty.
- **Progress:** due load, review history, retention/grade trends, fragile or suspended cards, and pending proposals/disputes. Charts must be based on stored review data and label their definitions.
- **Settings:** daily new/review limits, desired retention, default deck, card-generation preferences, AI provider/model configuration state, export/backup guidance, and account/security controls.

Prefer simple, accessible controls; keyboard support; clear answer-hidden/revealed states; readable long text; low-friction review; and no horizontal overflow at phone width. Avoid presenting an AI-generated score as an objective measurement of intelligence or factual correctness.

### Cards and card quality

A card is a schedulable unit with a stable identity and revisions. V1 card forms:

- Basic question/answer;
- reversed card, when explicitly enabled;
- cloze deletion for supplied text.

Each card supports a deck, tags, source links/locators, provenance, uncertainty, a canonical answer, optional explanation, and generation metadata. A card must test a focused proposition, distinction, procedure, mental model, or capability—not an entire book, conversation, article, or broad topic.

AI card-generation behavior:

- Generate a draft set from user-supplied notes/source or an explicitly selected Hermes memory snapshot.
- Keep each question answerable from its attached evidence. Mark unsupported inferences as model synthesis or uncertainty; never fabricate citations, quotations, source verification, or page references.
- Prefer meaningful retrieval and application over trivia, avoid ambiguous wording and multiple unrelated facts in one card, and flag likely duplicates.
- Return structured proposals that the learner can edit, remove, or approve individually. Never auto-publish generated cards.
- Preserve the exact prompt/model/config version used for generation without logging full source text or answers in operational logs.

### Review experience

- Present one question at a time and keep the answer hidden until the learner chooses to reveal it.
- Record a review event when the learner grades the answer. Support at least Again, Hard, Good, and Easy; optionally capture a typed response before reveal.
- Show the answer, explanation, source/provenance, and relevant uncertainty after reveal.
- Use Noesis's pinned FSRS library for due dates. AI must not set FSRS state, grade, stability, difficulty, or next-due values.
- Support undo/correction as a new auditable event or a controlled invalidation/rebuild flow; never silently erase review history.
- Make review sessions restart-safe. If a browser closes, the learner can resume without duplicate review events.
- Provide daily limits, due/new selection, suspension, archive, and maintenance behavior.

The web UI is the reliable review surface. Hermes can conduct conversational reviews through MCP when requested, but the app must not require a Hermes conversation to study cards.

### Hermes workflows

Through Hermes and MCP, the learner can ask to:

- find relevant memories and propose cards for a named topic;
- add a selected memory or conversation insight to a Noesis deck;
- retrieve what they have learned about a concept for a current task;
- check Noesis due load or study progress.

Hermes must show the proposed material and provenance before sending it. Noesis stores it as an inactive capture proposal; the learner reviews and activates it in the UI. For web-originated or pasted notes, the learner can use Noesis's own AI proposal flow without involving Hermes.

## 4. System boundary and architecture

### Noesis owns

The independent web application; authenticated application API; MCP API adapter; database/schema/migrations; accounts and authorization; decks, cards, card revisions, sources and provenance; proposals and approvals; immutable review events; FSRS scheduling and deterministic rebuilds; search; export/deletion; AI-provider configuration and request policy; and the homelab release/deployment lifecycle.

### Hermes Agent owns

Its own memory store and search/recall behavior; deciding what Hermes memory is relevant when the user requests it; natural-language interaction in Hermes; and using Noesis retrieval results in context. Hermes is not a database dependency of Noesis and does not operate the Noesis web UI on the user's behalf without an explicit request.

### Service shape

- A versioned Python application release with a browser-facing web UI, authenticated backend API, and authenticated MCP endpoint, all using the same Noesis application-service layer.
- The UI and MCP adapters must not implement separate business logic or write directly to database tables. Every mutation goes through the application service and audit/event rules.
- Production MCP uses Streamable HTTP with authentication so the Hermes process can connect to the separately deployed homelab service. A stdio adapter may remain for local development and isolated tests; it is not the production integration assumption.
- MCP sampling and elicitation are disabled. Noesis calls its configured AI provider directly for web-UI card generation and optional assistance; the MCP server never asks Hermes to generate text during a tool call.
- Use the homelab's established versioned native-Python/systemd release pattern: dedicated unprivileged service identity, immutable/versioned releases, explicit install/update/rollback scripts, durable state outside release directories, health checks, and preserve configuration/state on updates. Do not make Docker a production requirement merely because local test Compose files exist.
- Use the homelab's existing PostgreSQL service with a dedicated Noesis database and least-privilege Noesis role, independent of other applications' databases and roles. Noesis does not install, own, or administer PostgreSQL. Development/CI use a disposable database. If a PostgreSQL host is unavailable, deployment is blocked pending an explicit storage decision; do not silently ship an SQLite production variant that diverges from the homelab standard.
- Use numbered schema migrations, a documented backup and restore procedure, and test a restore into a separate database before enabling production use.
- Web and MCP listeners bind to loopback on distinct/configured ports unless the homelab's verified service topology requires a private container network. Remote access is through the existing authenticated private proxy/tunnel pattern, not a direct public bind. The reverse proxy identity gate does not replace Noesis app authentication/authorization.
- Keep the AI provider key, MCP bearer token, session signing secret, and database credentials in owner-only service secret files or the homelab's existing secret mechanism; never expose them to browser code, Git, public assets, process arguments, or ordinary logs.

The relevant homelab reference is the existing Marketmind service pattern: native versioned releases/systemd, an independent PostgreSQL service and role, and a separately protected web app. This is the default convention in the current workspace, not proof that a particular host, proxy, tunnel, database, or account is available.

### AI provider

The Noesis web UI requires AI-assisted proposal generation; the deterministic data/scheduler core remains independently testable and must work without inference for browsing, editing, and reviewing existing cards.

- Provide a provider adapter for an OpenAI-compatible endpoint, with provider/model/base-URL explicitly configured by the operator. A local/private inference endpoint is supported when it implements the required contract.
- Store secrets only in server-side configuration. The browser receives no model credential.
- Do not assume Hermes's API server shares Hermes memory or the exact same provider settings. It may be configured as a compatible inference endpoint only after its endpoint/auth/response format is verified; that provides model access, not memory access.
- Keep AI input scoped to the user-selected source/card set. Clearly identify external processing and the configured endpoint before the first upload to a non-local provider.
- Provide graceful failure: existing cards and review scheduling remain usable while the provider is unavailable or disabled.
- Persist model/provider ID and prompt/template version with generated proposals and assessments. Do not let generated output silently replace approved card revisions.

### Anki interoperability boundary

V1 implements its own card library and scheduling. It does not sync with AnkiWeb, alter an Anki collection, or guarantee compatibility with Anki scheduling/history. A future, separately scoped interoperability milestone may export UTF-8 text or `.apkg` packages after evaluating the maintained Anki package format and duplicate/update semantics. Imported/exported cards do not automatically preserve Noesis provenance, AI assessment evidence, or review history. Anki documents text and packaged-deck import: <https://docs.ankiweb.net/manual/importing/text-files> and <https://docs.ankiweb.net/manual/importing/packaged-decks>.

## 5. Data model

The existing learning domain remains useful, but the product must add or adapt it for a standalone flashcard application:

- **User/account:** authenticated local identity, authorization scope, preferences, and created/updated timestamps. Single-user homelab installation is the initial deployment target; avoid hardcoding a schema that prevents future multiple users.
- **Deck:** stable identity, name, parent/deck hierarchy if implemented, settings, lifecycle status, and ordering.
- **Source:** type, title/author, stable reference, version/edition, content hash, minimal excerpt or normalized text where permitted, locator, source revision, and capture actor. Include `hermes_memory` as a source kind, retaining an origin ID/reference when available but not relying on it for Noesis identity.
- **Card:** stable identity, deck, card type, tags, lifecycle/validity status, importance, desired retention, and current revision.
- **CardRevision:** front/question, back/canonical answer, optional explanation/cloze text, source links, provenance kind, uncertainty, generated model/template metadata, and author/approval metadata. Revisions are immutable.
- **CaptureProposal / ProposalItem:** inactive proposals, duplicate candidates, edits, per-item approve/reject decisions, expiry, and idempotency.
- **ReviewSession:** durable learner/deck selection and current card position; supports interruption and restart.
- **ReviewEvent / Attempt:** immutable review timestamp, scheduler grade, optional typed response, hints, latency/confidence where enabled, card revision, and validity.
- **Assessment:** optional AI-assisted feedback with evidence, missing elements, confidence, model ID, prompt/rubric version, and append-only status/dispute history. A user self-grade can drive scheduling according to explicit policy without pretending AI assessment is ground truth.
- **MemoryState / SchedulerTransition:** per-user/card FSRS state, due time, scheduler version, transition inputs/outputs, and rebuild status; never accepts scheduler state from the browser or model.
- **LearningPolicy:** daily limits, desired-retention default, new-card policy, provider-generation settings that are safe to store non-secret, and capture approval defaults.
- **AuditEvent / IdempotencyRecord:** append-only material mutations with actor, origin, correlation ID, request key, and safe payload metadata.

No automatic concept graph analytics, broad personal archive, or model-created fact authority is required for v1.

## 6. MCP surface

Expose only intent-oriented tools through the authenticated MCP endpoint; do not expose SQL, filesystem, or unrestricted CRUD. Adapt the current eight-tool surface as follows:

| Tool | Purpose |
| --- | --- |
| `propose_capture` | Create an inactive proposal from explicit user material or selected Hermes-memory snapshots; return proposal ID and duplicate/provenance summary. |
| `commit_capture` | Commit only item approvals explicitly recorded by the learner in Noesis; the agent cannot claim user approval on the learner's behalf. |
| `start_review` | Create/resume a durable conversational review and return the next question specification. |
| `submit_attempt` | Record an exact answer and optional evidence/self-grade; Noesis conditionally applies its deterministic scheduler transition. |
| `resolve_learning_issue` | Resolve disputes, bad questions, invalid attempts, or card corrections append-only. |
| `update_learning_state` | Change deck/card priority, retention, lifecycle, or policy without corrupting mastery history. |
| `recall_context` | Return relevant approved cards/learning evidence with provenance and uncertainty for Hermes to synthesize. |
| `get_progress` | Return due load, study progress, fragile units, pending proposals/disputes, and open sessions. |

For proposal approval, the UI is the authoritative confirmation surface. MCP `commit_capture` must require a proposal item decision that was recorded in the web UI, or be limited to creating a proposal until an explicit approval mechanism is implemented. Do not accept a model's statement that the user approved as equivalent to an authenticated user action.

All mutations require idempotency keys, authenticated actor identity, CSRF protection for browser mutations, structured validation errors, and rate limits appropriate to the local service. Scope every query and mutation to the authenticated Noesis user. MCP authentication is a separate machine credential with least privilege; do not reuse a browser session cookie as the MCP token.

Hermes client config targets the private/proxied Streamable HTTP MCP URL, uses a dedicated bearer token, sets `supports_parallel_tool_calls: false`, disables `sampling` and `elicitation`, and allowlists only the eight named tools. Exact Hermes MCP HTTP config and transport behavior must be verified on the deployment version before release.

## 7. Security, privacy, and operations

- Treat sources, Hermes memory snapshots, answers, assessments, provider requests, and review history as sensitive personal data.
- Require app authentication even when behind a private proxy. Do not rely on a hostname obscurity, a tunnel, or an edge redirect as the sole authorization boundary.
- Keep the service bound to loopback/private networking and put remote access behind the homelab's intended identity gate. Never bind the backend to `0.0.0.0` just to make a local proxy reach it.
- Apply per-user authorization to web/API/MCP reads and writes; use separate credentials for database, AI provider, MCP, and session signing.
- Keep secrets out of Git, client assets, query strings, command-line args, logs, exports by default, and browser telemetry. Redact provider and authorization headers from errors.
- Minimize source retention. Show source/provenance to the learner and allow explicit unlink/delete. Deleting a source must not silently erase an immutable review record; define and test redaction/tombstone behavior.
- Treat source text and AI-provider responses as untrusted input. Never treat imported memory/source content as system instructions.
- Provide database backup, off-host backup configuration, restore verification, export, and explicit destructive account/data deletion. Never claim backup exists until a restore test succeeds.
- Add health/readiness endpoints that reveal service/schema status without exposing data, secrets, or account details.
- Use structured logs with correlation IDs and operation metadata; never log complete source material, full AI prompts, user responses, cookies, bearer tokens, or provider keys by default.

## 8. Homelab deployment and release

The target is a service installed and maintained like other homelab applications, not a developer checkout running in a terminal.

### Production deployment shape

- Pin releases by version/tag/commit and package the application, locked dependencies, migration files, web assets, service units, and host deployment scripts as a reproducible release artifact.
- Run under a dedicated unprivileged service account, with versioned release directories and a stable `current` link or the homelab's equivalent release switch.
- Run the web/API/MCP application as a persistent systemd service with restart policy, restrictive umask, no-new-privileges, and only the filesystem/network permissions it needs. Do not run the process as root.
- Persist configuration/secrets and user uploads/source attachments outside the versioned release. Persist structured learning data in a dedicated PostgreSQL database/role on the independent homelab PostgreSQL service.
- Bind public-facing application ports to loopback. A private reverse proxy/tunnel provides access; protect the UI with the established homelab identity/access layer and preserve application authentication. MCP must have its own bearer token and may be reachable only from the Hermes host/network as configured.
- Provide first-install, upgrade, rollback, status, backup, restore-check, and uninstall procedures. Updates preserve database, secrets, identity configuration, and user content. Migrations must be forward-tested on a backup/fixture before production and rollback must state whether database downgrade is supported.
- Do not modify Hermes core, Hermes's memory database, shared reverse-proxy config, DNS, tunnel ingress, or PostgreSQL service configuration as a side effect of Noesis installation. Those are separately approved host changes.
- Provide a staging/acceptance deployment isolated from production data before first public/private-route promotion.

The project does not yet know the live homelab hostname, proxy/tunnel route, service account, PostgreSQL endpoint/role, or whether Hermes can reach that route. Discover those on the deployment host before writing exact production commands or claiming it is deployed.

### Operational commands (target CLI contract)

Provide commands equivalent to:

```text
noesis diagnose
noesis db upgrade
noesis export <path>
noesis backup
noesis restore-check <backup> --database <isolated-test-db>
noesis user list|create|disable
noesis delete-all --confirm DELETE-NOESIS
```

The precise commands may follow the repository's existing CLI conventions. Destructive operations require explicit confirmation and must report the exact target database before execution.

## 9. Implementation sequence

1. Preserve and test the existing domain/scheduler logic; define card/deck identity and user scoping.
2. Select and implement the production PostgreSQL adapter/migrations without silently changing current SQLite data. Provide a documented one-time migration/import if existing local data needs preservation.
3. Add authentication, authorization, audit events, idempotency, and service/API contracts.
4. Implement deck/card management and proposal review in the web UI.
5. Implement one-card-at-a-time review, self-grading, interruption/resume, and FSRS scheduling in the UI.
6. Add a server-side OpenAI-compatible provider adapter for optional AI card proposals/feedback, plus privacy and provider-failure handling.
7. Expose authenticated Streamable HTTP MCP backed by the same application services; keep local stdio only for dev/test if useful.
8. Update the Hermes skill and setup docs for remote MCP, memory-to-proposal capture, Noesis recall, and UI-based proposal approval.
9. Package versioned homelab releases and systemd lifecycle, PostgreSQL role/database setup instructions, backup/restore validation, and private-proxy integration notes.
10. Run automated tests, browser acceptance (desktop/mobile), MCP contract/security tests, clean install/upgrade/rollback tests, PostgreSQL backup/restore, and a live Hermes memory push/retrieval test.
11. Only after isolated acceptance passes, install to the intended homelab service path and verify authenticated UI, API, MCP and proxy path independently.

Do not claim homelab deployment from a local unit test or a working process alone.

## 10. Acceptance and release gate

### Product/UI

1. The app starts from a versioned release and is usable through authenticated desktop and mobile web interfaces.
2. A learner can create a deck, paste material, edit/approve/reject AI-proposed cards, browse/search cards, and inspect source/provenance.
3. A learner can complete a review entirely in the web UI, with the answer hidden until reveal, four grade choices, one persisted review event, and a Noesis-computed FSRS due date.
4. Closing/reopening the browser resumes an open review without duplicating an attempt.
5. AI-provider outage/disabled configuration does not prevent browsing, editing existing cards, studying, or scheduling.
6. Importance edits, corrections, deletion, disputed grading, and invalidation preserve the defined audit/history semantics.
7. Web/API/MCP operations are scoped to the authenticated user; unauthenticated and cross-user access is rejected.

### Hermes memory bridge

8. A Hermes MCP client connects to the actual private/proxied HTTP endpoint using the dedicated machine credential and discovers exactly the allowlisted tools; sampling and elicitation remain disabled.
9. With explicit user intent, Hermes retrieves a selected memory and submits a proposal tagged as a Hermes-memory source; Noesis does not search Hermes files/databases itself.
10. The web UI displays origin, timestamp/reference, content and generated cards; no proposal becomes active until the learner approves it in the UI.
11. A later request from Hermes to `recall_context` returns only Noesis-owned approved learning material and preserves source/provenance/uncertainty.
12. Hermes being stopped or its memory backend being unavailable does not make the Noesis UI, database, or review flow unavailable.

### Homelab/service

13. Install, upgrade, rollback, status, backup, and restore-check are exercised on an isolated homelab-like staging environment.
14. The service runs under its dedicated unprivileged account; app listeners bind only to loopback/private service networking; no unauthenticated public listener exists.
15. Noesis uses its own PostgreSQL database and least-privilege role. Restore from a backup to a separate database is verified before enabling production use.
16. The private proxy/tunnel path, edge identity gate, application auth, and MCP token are independently checked; a proxy redirect is not evidence that the origin or UI works.
17. The live URL, release identifier, systemd unit state, listener addresses, schema version, health result, access-control evidence, and backup/restore evidence are recorded without secrets.

### Test discipline

Automated unit, integration, migration, MCP, authorization and browser tests must pass. Use disposable databases and fixture data. Keep live-provider tests opt-in and avoid sending real memory or personal notes to a non-local provider without explicit approval. The acceptance report must distinguish local test results, isolated staging results and production observations. A mocked Hermes call is not a live memory bridge pass.

## 11. Current implementation and known gap

The repository currently contains a Python learning core with SQLite/FTS5, a stdio MCP adapter, explicit capture proposals, durable reviews, assessment/dispute handling, FSRS scheduling, export/delete/diagnostic commands, and a Hermes skill/config example. Its current automated suite reports 17 tests passing; Hermes discovered eight tools in an isolated scratch profile. Those checks do not satisfy the target architecture in this spec.

Not yet implemented in this checkout: standalone web UI; app accounts/authentication; PostgreSQL persistence and migration from existing SQLite; remote authenticated Streamable HTTP MCP production transport; in-app AI-provider adapter; homelab install/update/rollback/systemd packaging; verified backup/restore; and end-to-end live Hermes-memory-to-UI approval and recall. Do not describe Noesis as ready for homelab production until those gaps and acceptance gates are closed.

## 12. References

- Homelab service conventions: the existing Marketmind service uses native versioned releases/systemd, independent PostgreSQL, and a protected web app; this is a reference pattern in the current workspace, not a Noesis runtime dependency. The native systemd/release contract takes precedence over optional Compose examples.
- Hermes MCP feature guide: <https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp>
- Hermes MCP configuration reference: <https://hermes-agent.nousresearch.com/docs/reference/mcp-config-reference>
- Anki text-file importing: <https://docs.ankiweb.net/manual/importing/text-files>
- Anki packaged-deck importing: <https://docs.ankiweb.net/manual/importing/packaged-decks>

## Implementation addendum (2026-10-26)

The target requirements above remain unchanged. This checkout now implements a
standalone authenticated web application, scoped HTTP API, provider-backed draft
generation, self-graded FSRS reviews, authenticated Streamable HTTP MCP, PostgreSQL
configuration/migration branches, explicit SQLite transfer, and native release
artifacts. These additions are not production acceptance. The original learning
core and stdio interface remain a separate compatibility collection. See
[implementation evidence and remaining gaps](implementation-report.md),
[API semantics](web-api.md), and the [native runbook](deployment-native.md).
The historical gap description in section 11 describes the starting baseline.
