# Recipe Improvement Session HTTP Boundary

Status: implemented
Date: 2026-09-12
Related concept: ../concepts/2026-09-11-ai-assisted-recipe-improvement.md
Related specs: 2026-09-12-recipe-improvement-session-input.md, 2026-09-12-recipe-improvement-session-lifecycle.md, 2026-09-12-shared-ephemeral-text-sessions.md

## Outcome

A caller can initialize a recipe-improvement session over HTTP and read back its accepted snapshots and expiry while it is active. This exposes the existing validated session boundary without adding conversation or model behavior.

## Scope

- Add versioned HTTP operations to create and read one recipe-improvement session.
- Translate raw request data through the existing session-input validation before creating state.
- Return explicit invalid-input, unknown-session, and expired-session HTTP outcomes.
- No message submission, model invocation, proposals, streaming, UI, persistence, or Kochwiki access.

## Experience and UI Direction

Not applicable — this slice adds a backend HTTP contract only.

## Decisions and Behavior

- `POST /api/v1/recipe-improvement/sessions` accepts a JSON object with `source` and `foodstuffs` using the existing session-input schemas. The caller cannot provide a session ID, expiry, or derived availability index. Invalid input creates no session.
- At the JSON boundary, a source ingredient `amount` accepts a finite JSON number or decimal string and is converted to the existing strict internal decimal value before validation. Other source and foodstuff rules remain owned by the session-input boundary.
- Successful creation returns `201` with the service-generated `session_id` and absolute UTC `expires_at`.
- `GET /api/v1/recipe-improvement/sessions/{session_id}` returns `200` with `session_id`, `expires_at`, and the complete accepted `source` and `foodstuffs` snapshots. The derived availability-reference index remains internal; it is not caller-supplied or returned. Reading does not extend the fixed 90-minute lifetime.
- Invalid creation input returns `422`. Domain-validation failures expose the existing field-specific issue locations and messages. Malformed HTTP/JSON requests may use FastAPI's standard validation error representation.
- An unknown session ID returns `404`. An expired session still retained by the process returns `410`, without its snapshots. Opportunistic cleanup means a later request for that ID may return `404`.
- The HTTP operations use one process-local store instance within the serving process. They do not promise retrieval across restarts or workers.

## Contract

- Creation request: `{ "source": <RecipeImprovementSourceSnapshot>, "foodstuffs": <AvailableFoodstuffSnapshot[]> }`.
- Source ingredient `amount` is represented as a finite JSON number or decimal string; snapshot serialization may return the accepted decimal as a string.
- Creation response (`201`): `{ "session_id": <opaque string>, "expires_at": <UTC datetime> }`.
- Read response (`200`): `{ "session_id": <opaque string>, "expires_at": <UTC datetime>, "source": <accepted source snapshot>, "foodstuffs": <accepted foodstuff snapshots> }`.
- Domain input failure (`422`): `{ "kind": "invalid_input", "issues": [{ "location": <path>, "message": <text> }, ...] }`, with paths rooted at `source` or `foodstuffs`. The exact framework-generated body for malformed transport input is not part of this contract.
- Unknown (`404`) and expired (`410`) responses identify their outcome without returning session snapshots. Their precise error-body wording is not a client contract.

## Constraints

- Keep recipe input rules in the existing validation boundary and lifecycle rules in the existing session store; HTTP routing only adapts those contracts.
- No authentication or authorization mechanism is introduced by this slice. These snapshot-bearing endpoints must not be exposed to untrusted callers without an external access-control boundary; production exposure requires a separate security decision.
- No dependency, build, tooling, deployment, or frontend change is required.

## Acceptance Criteria

1. A valid JSON initialization request returns `201`, an opaque ID, and UTC expiry; a read with that ID returns the accepted source and foodstuffs, including the same expiry, without the derived index.
2. Invalid source or foodstuffs, including a source ingredient absent from the availability snapshot, return `422` with useful field locations and create no session.
3. An unknown ID returns `404`; a retained expired ID returns `410` without snapshots; a cleaned-up expired ID may later return `404`.
4. Reading a session does not renew its 90-minute expiry. The HTTP contract does not expose message append, model, proposal, tool, UI, or persistence behavior.
5. The route exercises the existing process-local lifecycle, not a fresh store per request; tests cover successful creation and read, validation failure, unknown ID, and expiry at the transport boundary.

## Risks

- Session IDs act as bearer references to potentially sensitive recipe snapshots. This contract is suitable only behind an access-control boundary until authentication and authorization are designed.
- Process-local storage makes reads fail after restart or when routed to another worker. This slice does not solve multi-worker routing or durability.
