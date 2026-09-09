---
name: noesis
description: Capture explicit learning material, run durable reviews, resolve grading issues, and recall learned context through Noesis.
version: 0.1.0
author: Noesis
license: MIT
metadata:
  hermes:
    tags: [learning, spaced-repetition, recall]
    category: productivity
---

# Noesis

Use the `mcp__noesis__*` tools. Noesis is the durable learning record and scheduler; you provide language understanding, question wording, and rubric-based assessment.

## Capture

Only capture after explicit intent such as “add this to Noesis.” You may offer capture, but never enroll ambient material silently.

1. Obtain the source through existing Hermes capabilities. Do not ask Noesis to read files, Obsidian, images, or the web.
2. Separate `source_claim`, `user_interpretation`, `hermes_synthesis`, and explicit uncertainty. Never invent a page, passage, heading, or verification claim.
3. Propose knowledge units narrow enough to test as one proposition, distinction, procedure, model, or capability. Give every unit an exercise specification with concrete required elements.
4. Call `propose_capture` with a fresh idempotency key. Present the returned proposal and duplicate warnings to the user.
5. Call `commit_capture` only after approval. Pass an approve/reject decision for each item and include user edits on approved items. Never infer approval from silence.

## Review

1. Call `start_review` with a fresh idempotency key. It may resume an unfinished durable session.
2. If it returns `nothing_due` or `budget_exhausted`, do not manufacture a review. In cron, respond with `[SILENT]`.
3. If it returns `awaiting_question`, generate exactly one question from the returned specification. Do not reveal the canonical statement or required elements.
4. Call `start_review` again with the session ID, exact question, model ID, prompt version, and a new idempotency key. Ask the recorded question only after this call succeeds.
5. When the learner answers, assess against the required elements and call `submit_attempt` with the exact question already recorded, exact answer, evidence, omissions, possible misconception, confidence, model ID, and rubric version.
6. Treat Noesis's scheduler result as authoritative. Never submit a grade, stability, difficulty, or next-due value directly.
7. Continue one question at a time while the session says `awaiting_question`. A process restart does not end a Noesis review session.

## Problems and disputes

- On “I disagree with that grade,” call `resolve_learning_issue` with `dispute_assessment`. Discuss the disagreement, then submit a replacement assessment or accept the learner's explicit self-grade. Never overwrite the original.
- For an ambiguous or factually wrong question, call `resolve_learning_issue` with the corresponding action and attempt ID. Do not count the attempt.
- For a corrected knowledge unit, show the correction and new rubric before committing it through `resolve_learning_issue`.

## Learning state

Use `update_learning_state` for importance, desired retention, suspension, resumption (`active`), maintenance, archiving, or learner policy. Explain that priority changes do not increase mastery.

## Contextual recall

During ordinary work, call `recall_context` when the user's learned material could materially help. Synthesize only from returned evidence, preserve its provenance and uncertainty, and do not present a user interpretation or Hermes synthesis as a verified source claim.

## Privacy

Keep excerpts minimal. Do not send complete books or vaults. Treat source material, questions, and answers as sensitive. Use opaque attachment references rather than copying large files.
