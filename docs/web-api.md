# Web and HTTP API contract

The primary application is the same-origin web app on port 8091. `noesis-web`
(or `python -m noesis.web.app`) binds only `127.0.0.1`. There is no frontend build
server or CDN dependency; packaged HTML/CSS/JavaScript are served directly.

The web product service lives in `application/web.py`. Its `app_*` tables coexist
with the legacy learning tables. Both use the pinned FSRS adapter. Legacy stdio
continues to use its existing service; it is a trusted local compatibility adapter,
not a production account authorization boundary. Remote MCP and browser/API
traffic share the new scoped product service and card collection.

## Authentication and requests

Accounts are provisioned with `noesis-admin user create USERNAME` (interactive
password prompt, minimum 14 characters). There is no public registration. Passwords
use salted scrypt. Sessions use 48-byte random opaque tokens, store only SHA-256
token hashes, expire after 12 hours, and check account disablement on every request.
Cookies are HttpOnly, SameSite=Strict, and Secure in production. There is no signing
secret because server-side opaque sessions do not need cookie signatures. Password
changes preserve the exact password, including surrounding whitespace, and revoke
all sessions. Passwords contain 14–1024 characters and are never trimmed. Login has
an eight-attempt/minute per-address limit;
authenticated requests have a 180/minute per-user limit. These are process-local;
run one web worker. Do not trust forwarded IP headers from arbitrary clients.

Optional single-user Access sign-in is disabled by default. Set
`NOESIS_ACCESS_ENABLED=true`; no email allowlist is required. Cloudflare Access
policy and the existing verifier are the identity authority. Optionally set
`NOESIS_ACCESS_EMAIL` to one exact email address for defense in depth. A nonempty
invalid value refuses startup; comparison uses casefolding only (no domain
matching, whitespace trimming or aliases).
`NOESIS_ACCESS_OWNER` defaults to `owner` and names an existing enabled account;
there is no automatic account creation or password replacement.

On each protected API request carrying `Cf-Access-Jwt-Assertion`, Noesis calls
`GET http://127.0.0.1:8790/verify` independently, sending only that assertion as
an application header. The verifier must return HTTP 200 with exactly one
`X-Hermes-Verified-Email` response header containing one valid human email. If the optional email restriction
is configured, that email must also match. The
address is fixed; proxies from the environment and redirects are not used. Missing
identity, malformed/duplicate/comma-joined assertions (maximum 16,384 characters),
invalid verifier responses and email mismatch cannot authenticate Access. Network
failure returns 503. API verification has a two-second overall deadline and connections have a
one-second socket timeout; verifier header
parsing uses Python HTTP limits, and verified email is capped at 254 characters.
Inbound `X-Hermes-Verified-Email` is always ignored. Never treat loopback clients
or the shared Caddy header alone as authenticated. The trusted verifier must
validate JWT signature, issuer, audience and expiry against the intended Access
application. **Expanding the Access policy shares the existing owner's data with
all admitted humans. The verifier audience may cover a wildcard application and
therefore multiple hostnames; verify its actual scope before relying on that
policy.** Noesis maps every accepted identity to the same owner.
A compromised verifier/local host can impersonate the configured user.
Noesis does not independently fetch keys or introspect Cloudflare revocation;
revocation behavior is limited to what the existing verifier enforces.

The existing UI automatically calls `/api/session` at boot: a valid Access identity
opens the workspace without a second login. Each Access request rechecks account
existence/disablement and the JWT. Access creates no password session or cookie.
Its CSRF token is an HMAC scoped to account and JWT digest using a random worker
secret; it remains stable until JWT rotation or process restart. Reload to obtain a
new token after either. Raw JWTs are never returned to JavaScript or application
logs. Run one worker, as with existing rate limits.

With no assertion, the ordinary password login/session path remains available,
for local fallback. Keep the listener loopback-only and public traffic behind
Access; do not expose password fallback as a separate public entry point. A supplied invalid assertion cannot fall back to a password
cookie. Removing the assertion after Access-only sign-in leaves no persistent
access; an independently established password session remains a deliberate fallback.
Noesis Sign out revokes password sessions and closes the workspace. Access users
see a closed-workspace explanation instead of a password form; it does not
invalidate an Access JWT or end the Cloudflare session. End that session through
Cloudflare Access logout. No logout URL is configured here, so the UI does not
guess a Cloudflare domain or redirect target; reloading with a still-valid JWT signs in again.
Public shell/assets and `/health` never call the verifier.

All browser POSTs, including login, require the configured exact `Origin` and JSON
content type. Authenticated POSTs additionally require `X-CSRF-Token` from
`GET /api/session` and `Idempotency-Key` (1–128 characters). The UI supplies these.
Retries with the same key and body return the prior response; changed bodies
conflict. Keys are scoped to account and operation. All object lookups verify
ownership, and account row locks serialize per-user PostgreSQL mutations.

JSON request bodies are limited to 100,000 bytes. The limit is checked as chunks
arrive, including requests without Content-Length; oversized bodies return 413
without buffering or consuming the remaining chunks.

API errors contain `error` and `correlation_id`; they never include SQL, provider
responses, or credentials. CSP blocks external scripts, framing and external
connections. Inline style attributes support data charts; scripts cannot run inline.

## Endpoints

| Method/path | Behavior |
| --- | --- |
| GET `/` and `/static/app.js`, `/static/style.css` | Public login shell/assets; no personal data |
| GET `/health` | DB connectivity; production additionally checks migration head |
| POST `/api/login` | Username/password; returns CSRF and sets session cookie |
| GET `/api/session`, `/api/me` | Account name/preferences; session also returns CSRF |
| POST `/api/logout` | Revokes all account browser sessions |
| POST `/api/password` | Current/new password, revokes all browser sessions |
| GET `/api/dashboard` | Stored counts, UTC activity and recent reviews |
| GET/POST `/api/decks` | List/create decks (`name`) |
| POST `/api/decks/ID` | Rename; or `delete:true, confirm:"DELETE"` archives deck/cards |
| GET/POST `/api/cards` | List/create cards (`deck_id`, `front`, `back`, optional provenance/tags) |
| GET `/api/cards/ID` | Current content, immutable revisions and review history |
| POST `/api/cards/ID` | Edit content into a new revision or change lifecycle |
| GET/POST `/api/proposals` | List/create inactive proposals with selected source and draft items |
| POST `/api/proposals/ID/decide` | One approve/reject decision per item, optional front/back/explanation/tags/uncertainty edits |
| GET `/api/provider` | Configured endpoint/model state, never credentials |
| POST `/api/generate` | `deck_id`, `source`, `consent:true`; server-side provider → inactive proposal |
| POST `/api/review/start` | Start/resume the account's open review; hidden answers omitted |
| POST `/api/review/reveal` | `session_id`; durably records reveal and returns answer/provenance |
| POST `/api/review/grade` | `session_id`, current `card_id`, integer `grade` 1–4, optional `response` |
| POST `/api/review/undo` | `review_id`, `reason`; append invalidation and rebuild schedule |
| POST `/api/settings` | `daily_limit` (1–1000), `new_limit` (0–1000), `retention` (.70–.99) |
| GET `/api/export` | Own current cards (including tombstones) and original review evidence/invalidation state |

Cards support `card_type:basic`, `reversed` (creates two independently scheduled
cards when explicitly selected), and `cloze`. A cloze front uses `{{c1::answer}}`;
all c1 spans form one deletion card. Separate c2/c3 card generation is not supported.
Optional fields: `source`, `source_type`, `origin`, `tags` (text), `explanation`,
`uncertainty`. Source snapshots retain capture timestamps. Proposal source text is
bounded to 30,000 characters and proposals to 30 cards. Generation is bounded to
12 cards, a 45-second timeout and five requests/minute/account. The exact system
prompt, template version, endpoint, model and request settings accompany drafts.
Provider URLs containing credentials, query parameters or fragments are rejected
and not exposed as browser configuration. Provider responses are untrusted plain text; the UI escapes all imported content.

## Scheduling and history semantics

Review answers are omitted until reveal (the authenticated card library is
intentionally inspectable). Keyboard: Space reveals, 1–4 grades; buttons and forms
also work without shortcuts. The session queue and revision IDs, position and reveal
state persist in the DB. A changed, archived, deleted or suspended queued card is
skipped. New cards follow due cards within the daily limit; limits reset at UTC
midnight and count recorded reviews, including later invalidations. An interrupted
session keeps its original queue. Settings affect subsequent sessions/transitions.

Each grade stores immutable revision-bound evidence and the exact FSRS input/output,
version, target retention and due date. Only server code sets scheduler state.
A unique session/position constraint prevents duplicate evidence. Undo retains
original evidence/transitions, appends an invalidation with a reason, and rebuilds
current memory from remaining evidence. The grade chart excludes invalidations;
recorded-review totals and activity include them. These are self-grade statistics,
not measured factual accuracy or an intelligence score.

Delete card removes it from the normal library and future review by retaining a
tombstone; revisions, source snapshots and evidence remain. Archive deck retains
its cards/history and leaves already-deleted tombstones deleted and hidden. These
are **not privacy erasure**. There is no account/data
privacy-purge UI, separate source-redaction operation, attachment storage, hierarchy,
default deck setting, or separate disputed-assessment workflow for web cards yet.
Legacy assessment/dispute APIs remain available only in the local legacy adapter.
