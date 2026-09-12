# Recipe Improvement Session Lifecycle

Status: implemented
Date: 2026-09-12
Related concept: ../concepts/2026-09-11-ai-assisted-recipe-improvement.md
Related specs: 2026-09-12-recipe-improvement-session-input.md

## Outcome

A validated recipe-improvement input can be held in a short-lived, backend-internal session and retrieved while valid. The session has service-generated identity and visible expiry, giving later conversation and proposal slices a lifecycle boundary without introducing those behaviors now.

## Scope

- Create a session from an already validated `RecipeImprovementSessionInput` and retrieve its snapshot by session ID.
- Expire sessions after a fixed lifetime and report unknown and expired IDs explicitly.
- No HTTP endpoint, conversation messages, model invocation, proposals, capability policy, persistent storage, or UI.

## Experience and UI Direction

Not applicable — this slice changes only internal backend state behavior.

## Decisions and Behavior

- The lifecycle accepts only the successful, immutable input from the existing session-input boundary; raw caller data must pass that boundary first. It retains the complete accepted source, foodstuffs, and derived availability index unchanged.
- Generate an opaque, unique session ID in service code. Creation returns that ID and an absolute UTC `expires_at` timestamp. Session IDs are not supplied by the model or caller.
- Use a fixed 90-minute lifetime measured from creation. Reads do not extend it. At or after `expires_at`, lookup fails and does not return the snapshot.
- Lookup distinguishes an unknown ID from an expired session still held by this process. Expired records may be discarded after reporting expiry; a later lookup of the same ID may therefore report unknown. Creation and lookup should discard expired records opportunistically so elapsed sessions do not accumulate indefinitely while the store is in use.
- The store must behave correctly under concurrent creation and lookup within one process. Stored input and returned session data must not be mutable through caller-held references.
- This is a recipe-improvement-scoped use of a simple session store, not a commitment to a generic cross-domain session framework. Other domains can share a storage abstraction later if their lifecycle needs warrant it.

## Contract

This is an internal, typed backend contract. Creation returns a session ID and expiry. Lookup returns either the unexpired session snapshot or an explicit `unknown`/`expired` result; it never returns an expired snapshot. No network or frontend contract changes in this slice.

## Constraints

- State is process-local and in memory. Restart loses sessions, and multiple service instances do not share them. No persistence or distributed-state mechanism is introduced.
- Keep time and ID generation service-owned and testable without waiting for real time. No dependency or build/tooling changes are required.

## Acceptance Criteria

1. Creating a session from accepted input yields a distinct opaque ID, an absolute UTC expiry 90 minutes after creation, and a retrievable snapshot equivalent to that input.
2. Lookup before expiry succeeds; lookup exactly at or after expiry fails explicitly and never exposes the snapshot. Reading before expiry does not change `expires_at`.
3. Unknown IDs fail distinctly from a first lookup of a held expired session. Cleanup may make later lookups of that expired ID unknown.
4. Caller mutation cannot alter a stored or retrieved session snapshot, and concurrent operations do not corrupt the store or reuse an active ID.
5. No HTTP, model, proposal, conversation, UI, Kochwiki access, or persistent-state behavior is added.

## Risks

- Process-local sessions are lost on restart and cannot be retrieved from a different instance. Horizontal scaling requires a later shared-store decision.
- Opportunistic cleanup runs only when the store is used. Expired entries can occupy memory during an idle period, and this slice does not set a live-session capacity or admission policy.
