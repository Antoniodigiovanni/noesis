# Noesis: Final Project Specification for Codex

## Your role

You are implementing and testing **Noesis**, a local-first personal learning system integrated with **Hermes Agent by Nous Research**.

Work autonomously within this specification, but do not silently expand the MVP. Inspect the actual environment and current Hermes documentation before making integration decisions. Do not claim completion until the live Hermes workflow has been exercised.

## Product vision

Noesis is a durable personal learning substrate. It records:

- what the user encountered;
- where it came from;
- what the user wants to understand, recall, distinguish, or apply;
- evidence of recall and understanding;
- mistakes, ambiguity, disputes, and corrections;
- relationships among concepts;
- learning priorities and preferences.

Spaced repetition is the first application, not the entire product. The same foundation should later support contextual recall, adaptive explanations, gap analysis, personalized curricula, misconception tracking, cross-domain synthesis, source re-entry, writing support, and portability across other agents.

The first release must prove only two user experiences:

1. Deliberate learning through capture and spaced review.
2. Contextual recall of learned material during ordinary Hermes work.

## Core architectural decision

Hermes is the first and primary **Learning Agent**. The external component is **Noesis Core**, a model-free deterministic service.

### Hermes owns

- conversation and user interaction;
- understanding natural-language learning requests;
- reading Obsidian notes through the user's existing Hermes integration;
- reading pasted notes, books, documents, and attachments;
- OCR or visual transcription when Hermes has an available capability;
- proposing concepts and knowledge units;
- generating natural-language exercises;
- assessing answers against structured rubrics;
- proposing corrections and conceptual relationships;
- asking for user approval;
- starting scheduled review workflows;
- delivering reviews through Hermes-supported surfaces.

### Noesis Core owns

- durable identities and revisions;
- sources and provenance;
- concepts and schedulable knowledge units;
- minimal typed relationships;
- durable review-session state;
- immutable attempts and assessments;
- user disputes, invalidations, and corrections;
- memory-model state and deterministic scheduling;
- importance, desired retention, lifecycle status, and policy;
- current-state tables and an append-only audit log;
- lexical retrieval and source-revision detection;
- idempotency, transactions, and concurrency invariants.

### Prohibited boundary violations

Noesis Core must not:

- configure or invoke an LLM;
- store an LLM provider credential;
- request MCP sampling;
- generate prose questions;
- decide factual truth from an unapproved model proposal;
- accept `next_due`, stability, or difficulty values from Hermes;
- become a replacement for Obsidian or a general personal archive.

Hermes must not:

- directly write scheduler state;
- treat its own memory or session database as the authoritative learning record;
- silently enroll ambiently detected material during the MVP;
- silently overwrite attempts, assessments, corrections, or source revisions.

## Product boundary

Store material only when it contributes to the user's epistemic or skill state: something they may want to understand, recall, distinguish, critique, connect, or apply.

Do not use Noesis for arbitrary files, tasks, daily chatter, contacts, or general life logging.

Obsidian is an optional source and destination. The user will not keep everything in Obsidian. Learning material may originate from:

- an explicit statement in a Hermes conversation;
- pasted notes;
- an Obsidian note or section;
- a book or textbook;
- notes plus the source book;
- notes without the original source;
- PDFs or other documents;
- web sources;
- handwritten-note images transcribed by Hermes.

## First inspect the environment

Before implementation:

1. Inspect the installed Hermes version and location.
2. Read applicable `AGENTS.md` files completely.
3. Inspect current Hermes MCP, skills, cron, gateway, and session behavior.
4. Confirm the exact stdio MCP configuration syntax.
5. Confirm how a Hermes skill is installed and discovered.
6. Confirm how cron delivery can lead into a continuable user conversation.
7. Record the exact Hermes version and commands used.
8. Avoid modifying Hermes core. If MCP plus a Hermes skill cannot support a required behavior, stop and explain the blocker before proposing a core patch.

## Technical shape

Build Noesis as a separate repository and process using a modular-monolith structure.

Suggested structure:

```text
noesis/
  domain/
  application/
  persistence/
  scheduler/
  retrieval/
  mcp/
  cli/
  integrations/hermes/
  tests/
  migrations/
```

Use a supported Python version compatible with the environment, but keep Noesis in its own virtual environment.

Prefer:

- Pydantic for contracts;
- SQLAlchemy for persistence;
- Alembic for migrations;
- SQLite with WAL mode and FTS5 for the MVP;
- the maintained official MCP Python SDK;
- a maintained FSRS implementation behind an adapter.

Do not add PostgreSQL, a vector database, a distributed queue, a web UI, or microservices in the MVP.

The canonical internal boundary is the application-service interface. The stdio MCP adapter and tests call that interface directly. Do not make the MCP adapter call an HTTP server over localhost.

Design the application interface so that an HTTP adapter can be added later, but do not implement HTTP merely for hypothetical portability unless it is essentially free after the core is complete.

## Hermes MCP configuration

Use stdio MCP for the first integration. Generate a configuration example based on the actual installed Hermes version.

It should be equivalent to:

```yaml
mcp_servers:
  noesis:
    command: "/absolute/path/to/noesis/.venv/bin/python"
    args: ["-m", "noesis.mcp"]
    supports_parallel_tool_calls: false
    sampling:
      enabled: false
    elicitation:
      enabled: false
```

Requirements:

- Explicitly disable MCP sampling so Noesis cannot request Hermes inference.
- Explicitly disable MCP elicitation. Reviews may remain unanswered for hours, so durable review sessions—not a blocking MCP form—must handle asynchronous interaction.
- Leave parallel tool calls disabled because mutating operations share SQLite state.

## MVP domain model

Implement the following entities with stable IDs and timestamps.

### Source

Represents material encountered by the user.

Required data:

- source type;
- title and optional author;
- external reference or attachment reference;
- edition/version where relevant;
- content hash;
- captured excerpt or normalized text where permitted;
- locator such as page, heading, block, timestamp, or image region;
- parent/source-bundle relationship;
- metadata and capture actor.

### Concept

A lightweight stable grouping identity, such as “dichotomy of control” or “Bayesian updating.”

Required data:

- title;
- short description;
- lifecycle status.

Do not implement graph analytics or automated concept merging.

### KnowledgeUnit

The principal schedulable object. It is narrower than a topic and represents one proposition, distinction, procedure, mental model, or capability.

Required data:

- concept ID;
- kind;
- canonical statement;
- source links and locators;
- revision;
- importance;
- desired retention;
- lifecycle status: proposed, active, suspended, maintenance, archived;
- validity status;
- creation actor.

Importance and desired retention are not mastery. Changing either must not rewrite review history or falsely increase memory strength.

### ConceptEdge

Implement only a minimal relationship table supporting:

- `prerequisite_of`;
- `contrasts_with`;
- `related_to`.

Store provenance and proposal/approval status. Distinguish source-asserted relationships from Hermes-synthesized ones. Do not implement automatic traversal, graph scoring, or visualization.

### ExerciseSpecification

Describes the capability to test without fixing the wording.

Supported initial exercise types:

- free recall;
- explain in own words;
- compare/contrast;
- application to a scenario.

Store required elements, acceptable alternatives, common errors, and difficulty target.

### ExerciseInstance

Stores the exact question generated by Hermes, its specification/version, the generation context reference, and creation metadata.

The scheduler attaches to the `KnowledgeUnit`, not to every wording variation.

### ReviewSession

Required because Hermes cron and messaging conversations are asynchronous.

Store:

- learner ID;
- selected knowledge-unit IDs;
- current position;
- current exercise-instance ID;
- status: created, awaiting_question, awaiting_answer, awaiting_resolution, complete, expired, cancelled;
- origin/delivery metadata when supplied by Hermes;
- creation and expiry timestamps.

The workflow must survive process restarts and later messages. Do not depend on the cron process or one agent turn remaining alive.

### Attempt

Attempts are immutable. Store:

- review session and exercise IDs;
- exact user response;
- hints used;
- latency where available;
- user confidence/self-grade where available;
- validity status;
- timestamps.

### Assessment

Assessments are immutable and independently disputable. Store:

- recall outcome;
- evidence;
- missing required elements;
- possible misconception text;
- assessor confidence;
- model identifier;
- rubric/prompt version;
- status: proposed, accepted, disputed, superseded, ungradable;
- timestamp.

### MemoryState

Store the pinned scheduler's state per learner and knowledge unit, including last review, next due, and scheduler version.

### Policy

Support at least:

- daily item budget;
- default desired retention;
- importance defaults;
- low-confidence assessment threshold;
- maintenance probe policy;
- capture approval default.

### Event

Maintain an append-only audit/domain-event table for every material mutation.

Include:

- event ID;
- aggregate type and ID;
- event type;
- payload;
- actor;
- source system;
- correlation ID;
- idempotency key;
- model and prompt version where applicable;
- timestamp.

Do not build a general event-sourcing framework. Normalized tables are the normal source for current-state queries. Only scheduler state affected by disputed or invalidated attempts must support deterministic rebuild in the MVP.

## Scheduler contract

Use a maintained FSRS library and pin its exact version. Do not implement FSRS formulas from memory.

Hide it behind an interface equivalent to:

```text
schedule(memory_state, grade, reviewed_at, desired_retention)
  -> new_memory_state, next_due, explanation
```

Keep two concerns separate:

- FSRS answers: “After this assessment, when should this unit next be reviewed?”
- Selection policy answers: “Which eligible unit should be reviewed now?”

Initial selection considers:

- due/overdue status;
- importance;
- demonstrated weakness;
- recent repetition;
- topic diversity;
- daily budget.

Do not put importance or selection-policy factors into FSRS memory state.

Maintenance mode is not permanent graduation. It produces rare probes and returns to active after failure, correction, source revision, or renewed relevance.

## Assessment contract

Hermes submits semantic evidence using this constrained shape:

```json
{
  "recall_outcome": "failed | difficult | successful | effortless | ungradable",
  "evidence": ["Correctly identified what is outside personal control"],
  "missing_elements": ["Did not distinguish action from outcome"],
  "possible_misconception": null,
  "assessor_confidence": 0.87,
  "user_confidence": 0.65,
  "model_id": "provider:model",
  "rubric_version": "rubric-v1"
}
```

Noesis maps outcomes deterministically:

| Outcome | FSRS grade |
| --- | --- |
| failed | Again |
| difficult | Hard |
| successful | Good |
| effortless | Easy |
| ungradable | No scheduler update |

If assessor confidence is below policy or the user disagrees, preserve the attempt and assessment, place the review session in `awaiting_resolution`, and do not finalize the scheduler update.

Resolving a dispute creates a new assessment or accepts a self-grade. Never rewrite the original assessment.

If an exercise or attempt is later invalidated, preserve history and deterministically rebuild that unit's scheduler state from the remaining valid attempts.

## Source and capture behavior

Capture is explicit-only in the MVP.

Hermes may react to statements such as:

- “Add this to Noesis.”
- “Add concept X from my Obsidian note Y.”
- “I read this book and took these notes; add them to my learning system.”
- “Transcribe these handwritten pages, show me uncertain parts, and propose learning material.”

Flow:

1. Hermes obtains or transcribes the source.
2. Hermes identifies source claims, user interpretations, uncertainties, and proposed knowledge units.
3. Hermes calls `propose_capture`.
4. Noesis validates, detects exact/lexical duplicates, and returns a proposal summary.
5. Hermes shows the proposal to the user.
6. Hermes calls `commit_capture` only for approved or edited items.

Preserve distinctions such as:

```text
The source states X.
The user interpreted Y.
Hermes proposed connection Z.
The user approved Z.
```

If the original book is not available, record bibliographic context but treat the user's notes as the available source. Do not fabricate page or section references or claim verification against the book.

For Obsidian, Hermes reads the note through its existing access. Noesis stores only the stable vault/note reference, locator, content hash, relevant excerpt, and metadata. Do not build an Obsidian connector into Noesis for the MVP.

For OCR, Hermes performs transcription. Noesis stores the supplied original reference, file hash, page/region locator, raw transcription, corrected transcription, and confidence. Material uncertainties that change meaning require approval.

## MCP tool surface

Expose exactly these intent-oriented tools unless implementation reveals a strong reason to adjust them:

### `propose_capture`

Validate a structured source/concept/knowledge proposal, identify likely duplicates, and create an inactive proposal.

### `commit_capture`

Commit approved or edited proposal elements transactionally.

### `start_review`

Create or resume a durable review session and return the next exercise specification, source context, recent exercise types to avoid, and selection explanation.

### `submit_attempt`

Record the exact exercise, immutable response, and structured assessment. Apply the deterministic scheduler transition only when the assessment is accepted and sufficiently confident.

### `resolve_learning_issue`

Handle:

- disputed grading;
- ambiguous or factually wrong questions;
- invalid attempts;
- corrected knowledge units;
- revised source interpretations.

### `update_learning_state`

Change importance, desired retention, lifecycle status, suspension, resumption, or maintenance state without corrupting mastery history.

### `recall_context`

Retrieve relevant concepts, knowledge units, user interpretations, uncertainties, and source references for a natural-language task context using FTS5 and explicit relationships. Return evidence for Hermes to synthesize; do not generate a final answer.

### `get_progress`

Return due load, recent assessments, lifecycle counts, fragile units, maintenance items, and concise explanations.

All mutations require idempotency keys. Return stable IDs, structured validation errors, conflict information, and concise summaries.

Do not expose unrestricted CRUD, filesystem, or SQL-like MCP tools.

## Hermes skill

Create a concise Hermes skill named for Noesis. It should contain procedure, not durable learning content.

Teach Hermes:

- when explicit capture intent exists;
- how to distinguish sources, user interpretations, and its own synthesis;
- how to propose narrow knowledge units;
- how to present an approval summary;
- how to generate one question at a time;
- how to assess against required elements;
- how to record model/rubric metadata;
- how to resume a durable review session;
- how to handle “I disagree with that grade”;
- how to flag a bad question;
- how to update importance or suspension;
- how to call contextual recall during ordinary work;
- how to avoid silently creating learning material.

Do not add ambient capture automation in the MVP. Hermes may ask whether the user wants to add something, but it must not enroll it without explicit confirmation.

## Downstream compatibility

Do not implement full features for the following, but avoid schema choices that make them impossible:

- adaptive explanation based on demonstrated knowledge;
- prerequisite and learning-gap analysis;
- personalized curriculum generation;
- misconception targeting;
- cross-domain synthesis;
- re-entering the context of an old book or paper;
- writing and teaching support;
- recall of relevant learned principles during decisions;
- an HTTP adapter for other agents;
- richer concept-graph analysis.

Contextual recall is the only non-review downstream feature required in the MVP.

## Tests

### Unit tests

Cover:

- schema/domain invariants;
- source hashing and revisions;
- explicit proposal and approval behavior;
- idempotent mutations;
- duplicate detection;
- lifecycle transitions;
- importance versus mastery separation;
- fixed-clock FSRS adapter behavior;
- review-session persistence and expiry;
- low-confidence assessment gating;
- dispute resolution;
- invalid-attempt scheduler rebuild;
- maintenance reactivation;
- selection budget and diversity;
- audit-event creation;
- SQLite transaction conflicts.

### MCP tests

Test every tool's:

- success path;
- validation errors;
- idempotent retry;
- state conflict behavior;
- persistence across process restart.

Prove that Noesis makes no LLM call and requires no model credential.

### Live Hermes acceptance test

Run against the actual installed Hermes runtime, not only a mocked client.

1. Start a fresh Hermes conversation with the Noesis stdio MCP and skill enabled.
2. Confirm Hermes discovers the eight tools.
3. Send:

   > I read *Meditations* by Marcus Aurelius and took these notes. Add them to Noesis, but show me the proposed concepts before activating them: “I cannot control other people's choices, but I can control how deliberately I respond. Marcus repeatedly uses impermanence to reduce the emotional weight of status and conflict. I am not sure whether this means suppressing emotion or changing the judgment behind it.”

4. Verify Hermes proposes narrow concepts and knowledge units.
5. Verify it distinguishes user uncertainty from a source claim and does not invent passage references.
6. Approve at least two units and edit or reject one.
7. Verify sources, concepts, units, approval state, events, and provenance.
8. Make one unit due through a clearly test-only fixed-clock or fixture mechanism.
9. Start a review and verify a durable review-session record exists.
10. Answer partially or with difficulty.
11. Verify Hermes submits evidence and Noesis—not Hermes—calculates scheduler state.
12. Say: “I disagree with that grade.” Verify the original assessment remains, the update is held or superseded correctly, and the dispute can be resolved.
13. Mark the question ambiguous. Verify the attempt can be excluded and scheduler state rebuilt without deleting history.
14. Increase importance. Verify mastery is unchanged.
15. Suspend and resume the unit.
16. Restart Noesis and resume an unfinished review session.
17. In an ordinary conversation ask:

   > What ideas I have learned might help me distinguish what I can influence from what I cannot?

18. Verify contextual recall returns the learned material with provenance and Hermes uses it without overstating source certainty.

### Optional Obsidian acceptance path

If the user's Hermes Obsidian integration is available:

1. Use a clearly identified disposable note or section.
2. Ask Hermes to add that section to Noesis.
3. Verify the stored source reference, locator, excerpt, and content hash.
4. Modify the note and recapture.
5. Verify Noesis creates or proposes a source revision rather than silently overwriting established knowledge.

If unavailable, report the exact blocker and mark this path skipped. Do not simulate a live pass.

### Optional OCR acceptance path

If Hermes has usable OCR/vision capability, attach a handwritten test page with one deliberately ambiguous word. Verify provenance and uncertainty handling.

If unavailable, test Noesis with a structured OCR fixture and mark the live Hermes OCR path skipped. Do not add an OCR or LLM provider to Noesis.

## Security and privacy

- Use stdio and local storage by default.
- Store no model credentials.
- Do not copy complete books or vaults when excerpts and stable references suffice.
- Treat source text and learning records as sensitive.
- Do not log full source passages or answers by default.
- Sanitize untrusted source material before Hermes uses it as prompt context.
- Keep original scans and large attachments behind opaque references.
- Provide explicit export and deletion commands at the application/CLI level.
- Make test-only clock manipulation impossible to enable accidentally in normal operation.

## Observability and diagnostics

Use structured logs with correlation IDs across MCP calls, application operations, event commits, and scheduler transitions.

Provide a diagnostic CLI command reporting:

- Noesis and schema versions;
- scheduler implementation and pinned version;
- database health;
- counts by lifecycle state;
- pending captures and disputes;
- open review sessions;
- failed scheduler rebuilds;
- MCP startup status.

## Implementation sequence

Implement in this order:

1. Domain model, migrations, repositories, and audit events.
2. Capture proposal and approval.
3. Scheduler adapter and deterministic fixed-clock tests.
4. Durable review sessions.
5. Exercise and attempt recording.
6. Assessment gating and scheduler updates.
7. Dispute, bad-question, correction, and rebuild paths.
8. Learning-state controls.
9. FTS5 contextual recall.
10. MCP adapter.
11. Hermes skill and configuration.
12. Automated test suite.
13. Live Hermes acceptance test.
14. Optional Obsidian and OCR tests when capabilities exist.

Do not implement future features before the vertical slice passes end to end.

## Definition of done

The project is complete only when:

- Noesis runs without LLM configuration;
- MCP sampling and elicitation are explicitly disabled;
- Hermes provides all language reasoning with its existing model;
- Hermes discovers the Noesis MCP tools without a Hermes core modification;
- explicit capture, proposal review, and approval work;
- review sessions survive later messages and process restart;
- a real attempt produces a deterministic scheduler transition;
- a disputed grade and bad question can be resolved without deleting history;
- scheduler state can be rebuilt after invalidation;
- importance changes do not alter mastery;
- suspension and maintenance state work;
- contextual recall works with provenance;
- automated tests pass;
- the live Hermes test is documented with actual commands and observed results;
- unavailable Obsidian or OCR paths are honestly marked skipped.

## Final report

At completion, return:

1. Architecture summary.
2. Files created or changed.
3. Domain and database schema summary.
4. MCP tool-contract summary.
5. Exact setup and launch commands.
6. Exact Hermes configuration and skill installation steps.
7. Automated test results.
8. Live Hermes acceptance-test evidence.
9. Optional test paths completed or skipped, with blockers.
10. Known limitations and recommended next iteration.

Do not report a mocked interaction as a live Hermes test. Do not claim a feature works unless its acceptance criterion has been exercised.

