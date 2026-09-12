# Recipe Improvement User-Message HTTP Boundary

Status: implemented
Date: 2026-09-12
Related concept: ../concepts/2026-09-11-ai-assisted-recipe-improvement.md
Related specs: 2026-09-12-recipe-improvement-session-http-boundary.md, 2026-09-12-shared-ephemeral-text-sessions.md

## Outcome

A caller can append user text to an active recipe-improvement session over HTTP and read the ordered conversation back. This exposes the existing shared text-session behavior without starting model turns.

## Scope

- Add an HTTP operation for appending one user message to an existing recipe-improvement session.
- Include ordered text messages in the existing session read response.
- No assistant-message submission, model invocation, generated reply, streaming, proposals, UI, or persistence.

## Experience and UI Direction

Not applicable — this slice changes only the backend HTTP contract.

## Decisions and Behavior

- `POST /api/v1/recipe-improvement/sessions/{session_id}/messages` accepts `{ "text": <string> }`. The server assigns the `user` role; a caller cannot supply a role or other message fields.
- A successful append returns `201` with the accepted `{ "role": "user", "text": <submitted text> }`. Text is retained exactly as submitted, including surrounding whitespace.
- The existing session GET response adds `messages`, an array of `{ "role": "user" | "assistant", "text": <string> }` in append order. A newly created session returns an empty array. The response can represent assistant messages retained by the shared core, but this slice provides no HTTP operation for creating them.
- Blank or whitespace-only text and text longer than the shared core's 4,000-character limit return `422`. A session at the shared core's 100-message limit returns `409`. A rejected append does not change the conversation.
- An unknown ID returns `404`. A retained expired ID returns `410`; after cleanup, it may return `404`. Neither outcome exposes messages or snapshots. Append and read do not extend the fixed 90-minute expiry.

## Contract

- Append request: `{ "text": <string> }`; extra fields are rejected.
- Append response (`201`): `{ "role": "user", "text": <string> }`.
- Active session read (`200`) retains `session_id`, `expires_at`, `source`, and `foodstuffs`, and adds `messages: [{ "role": <role>, "text": <string> }, ...]`.
- Invalid message (`422`), limit reached (`409`), unknown (`404`), and expired (`410`) are distinct outcomes. The exact error-body wording is not a client contract; malformed transport requests may use the framework's standard validation response.

## Constraints

- Reuse the existing recipe session store and shared text-session validation and limits; do not duplicate conversation state in the HTTP layer.
- No authentication or authorization is added. Session IDs remain bearer references to potentially sensitive snapshots and messages, so these endpoints must not be exposed to untrusted callers without an access-control boundary.
- The store remains process-local; cross-worker retrieval and restart recovery are not promised. No dependency, build, tooling, deployment, or frontend change is required.

## Acceptance Criteria

1. A newly created session reads back with `messages: []`. Appending two user messages returns `201` for each, and a subsequent read returns both in order with exact submitted text.
2. A caller cannot set the message role or additional fields; rejected requests do not append anything.
3. Blank, whitespace-only, and over-4,000-character text return `422`; the 100-message limit returns `409`. Rejected appends leave the ordered messages unchanged.
4. Unknown and expired append outcomes return `404` and `410` respectively, without exposing session content. Append and read preserve the original expiry.
5. The HTTP operation uses the same process-local store as session creation and retrieval. No model, assistant-reply, proposal, or streaming behavior is introduced.

## Risks

- Adding messages to the read response changes an internal backend/frontend contract, though no frontend consumer exists yet. Consumers should tolerate the new field.
- Without access control, possession of a session ID permits reading and appending to its conversation. Production exposure needs a separate security decision.
