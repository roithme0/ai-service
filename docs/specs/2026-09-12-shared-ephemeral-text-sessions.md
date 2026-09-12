# Shared Ephemeral Text Sessions

Status: implemented
Date: 2026-09-12
Related concept: ../concepts/2026-09-11-ai-assisted-recipe-improvement.md
Related specs: 2026-09-12-recipe-improvement-session-lifecycle.md, 2026-09-12-recipe-improvement-session-input.md

## Outcome

The backend has a small, domain-neutral core for short-lived sessions and ordered text conversation. Recipe improvement uses that core instead of owning a separate expiry mechanism, while its validated recipe and foodstuff snapshots remain recipe-specific.

## Scope

- Move the existing process-local session identity, fixed expiry, lookup, and cleanup behavior into a reusable backend core.
- Add ordered, bounded user and assistant text messages to active sessions, with atomic append and read behavior.
- Adapt recipe-improvement session creation and lookup to the shared core without changing its accepted input or 90-minute expiry.
- No HTTP, frontend, model invocation, streaming, cancellation, tool calls, proposal artifacts, or conversation persistence.

## Experience and UI Direction

Not applicable — this slice changes only internal backend state and contracts.

## Decisions and Behavior

- The core owns session IDs, absolute UTC expiry, expiry checks, opportunistic cleanup, and concurrency protection. A session is created with a validated, typed domain payload and a fixed lifetime supplied by its consumer. The recipe consumer uses 90 minutes. Reads and appends do not renew expiry.
- The core treats the payload as opaque: it does not import recipe models, inspect foodstuffs, or apply domain rules. It retains an owned snapshot and does not expose caller-mutable state. Recipe input validation remains at the existing recipe boundary.
- A conversation starts empty. Each accepted message has exactly one role (`user` or `assistant`) and nonblank text. Text is preserved as submitted, including surrounding whitespace; a whitespace-only message is rejected. No system, tool, or artifact message type is introduced yet.
- Messages are returned in append order. Concurrent appends are serialized so neither messages nor their ordering are lost. A rejected append leaves the conversation unchanged.
- Bound each session to at most 100 messages, each at most 4,000 characters. An append past either limit fails explicitly. These are protective per-session limits, not a model context/token policy.
- At or after expiry, neither lookup nor append exposes or changes the session. Preserve the existing distinction between an unknown ID and the first lookup of an expired record still held by the process; opportunistic cleanup may make a later operation report unknown. Apply the same lifecycle semantics to append.
- Existing recipe-improvement session behavior is migrated to the core, not duplicated behind a second recipe-specific store. No legacy compatibility is required for the current internal Python interface, but its observable creation and lookup outcomes remain equivalent.

## Contract

This is an internal, typed Python contract. Creation returns an opaque service-generated ID and UTC expiry. An active-session read returns the owned domain payload, expiry, and ordered text messages. Append accepts a session ID, role, and text and returns an explicit accepted, unknown, expired, invalid-message, or limit-reached outcome. A read returns active, unknown, or expired. No network contract changes.

## Constraints

- Keep the core independent of recipe improvement, Kochwiki, model providers, and transport frameworks. Do not introduce a general streaming, tool-call, or artifact abstraction in anticipation of later slices.
- Retain process-local, in-memory storage and the existing fixed-from-creation expiry semantics. Restarts and cross-instance reads remain unsupported.
- No dependency, build, tooling, or deployment configuration change is required.

## Acceptance Criteria

1. A recipe-improvement session still accepts only validated recipe input, receives a unique service-generated ID, expires exactly 90 minutes after creation, and yields the same recipe snapshot while active.
2. The shared core can hold a different typed payload without importing recipe code; its lifetime is supplied by the consumer, and reads or appends do not extend it.
3. Active sessions start with no messages; valid user and assistant messages are returned in append order with text unchanged. Concurrent appends retain every accepted message in one deterministic order.
4. Blank or oversized text, unsupported roles, and appends beyond 100 messages fail explicitly without changing stored state.
5. Reads and appends at or after expiry fail explicitly without exposing payload or messages. Unknown IDs and held expired IDs are distinguishable as specified; cleanup behavior remains safe under concurrency.
6. Caller mutation of supplied payload or returned session data cannot alter stored state. No HTTP, model, UI, proposal, streaming, tool-call, or persistent-state behavior is added.

## Risks

- In-memory state is lost on restart and is not shared between processes. This slice does not add a live-session capacity or idle-time memory reclamation.
- Character and message limits prevent unbounded individual conversations but do not ensure a model's context window will fit. A later model-integration slice must define context selection and token budgeting.
- Future streaming and artifacts may require a richer turn structure. This slice promises only ordered text messages, not a stable external message schema.
