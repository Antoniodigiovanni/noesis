# Architecture

The canonical boundary is the in-process application service interface. The MCP adapter is deliberately thin and never calls an HTTP service. SQLite normalized tables answer current-state queries; `events` is an append-only audit log rather than a general event-sourcing framework.

Stable `Source` and `KnowledgeUnit` identities have immutable revision rows. Attempts and assessments retain their originally recorded fields. Later assessment-status and attempt-validity decisions are append-only records. `MemoryState` is a rebuildable projection derived from accepted, valid evidence through the pinned FSRS adapter.

All mutating MCP operations require idempotency keys. SQLite uses foreign keys, WAL mode, a busy timeout, and immediate write transactions. FTS5 provides local lexical retrieval. Noesis imports no LLM SDK and performs no inference.

