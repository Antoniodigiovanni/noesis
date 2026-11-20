# Architecture

The primary product boundary is `application/web.py`: authenticated browser/API
and remote MCP adapters share its scoped deck/card/proposal/review service. They do
not write database tables directly. Accounts, login sessions, decks, immutable card
revisions, inactive proposals, study sessions, immutable review evidence and
append-only invalidations live in `app_*` tables. Database-backed opaque sessions
and per-user object ownership protect the web API; a separate fixed-account bearer
credential protects remote MCP. Each mutation records an audit event and an
account-scoped idempotency response. PostgreSQL account locks and SQLite immediate
transactions serialize mutations. The FSRS adapter alone computes memory state.

Production uses a configured dedicated PostgreSQL DB through SQLAlchemy/psycopg;
SQLite remains for local development/tests. Numbered migrations add the app tables
without changing legacy table shapes. Startup does not migrate production state.
Read `deployment-native.md` for the explicit read-only SQLite backup transfer and
its limitations. PostgreSQL runtime acceptance remains unverified in this sandbox.

The original `application/service.py` learning service remains compatible with the
trusted local stdio MCP adapter. Its sources/knowledge units, immutable revisions,
attempts, assessment/validity events and rebuilds are retained. They are separate
from the web card collection; automatic adoption of legacy units/questions/history
into app accounts is not implemented. SQLite retains FTS5; PostgreSQL legacy recall
uses a narrower statement-only lexical fallback. Web/remote recall searches approved
web cards and preserves source snapshots and uncertainty.

Provider requests use a server-only OpenAI-compatible adapter, explicit source
selection/consent, bounded requests and structured untrusted output. The browser
never receives a provider key. Generation creates drafts, never approved revisions.
Review is self-graded and independent of inference. No source text is interpreted
as executable HTML or trusted system instructions. Noesis never inspects Hermes
memory or calls sampling/elicitation callbacks.

Native release artifacts package locked dependencies, assets, migrations, hardened
systemd units and operator lifecycle/backup scripts. Both listeners bind loopback;
production proxy routing and the independent PostgreSQL DB are operator-provisioned.
The current uncommitted checkout is also running as a user-level preview behind the
existing Cloudflare Access gate, using isolated SQLite data; this is not production
acceptance. See `deployment-native.md` for the exact preview/production boundary.
