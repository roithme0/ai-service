# Native Conversation State

## Status

Approved for delivery on 2026-10-21. The requested slice adopts Pydantic AI's native conversation state while retaining process-local, in-memory sessions. No database, restart recovery, checkpointing, or durable execution is included. Implemented through the Deliver Spec workflow. Backend and frontend validation passed.

## Goal

Use Pydantic AI's `Conversation` as the retained model-facing state for a conversation. Compose application-owned session information around that state rather than recreating framework messages, usage, identity, or deferred-tool state. Establish a clear serialization boundary for a later persistence slice without adding storage infrastructure now.

This is an in-memory state cutover, not durable persistence. Pydantic AI supplies the state model and serialization; the application continues to own session storage and access.

## Current Implementation

`SessionState` owns a native `Conversation`, `turn_executions`, and accepted session artifacts. The native value retains messages, cumulative usage, identity and deferred-tool state. Each `TurnExecution` retains lifecycle metadata and, only while active, a `TurnObservation` for live inspection and notifications. Settlement releases the observation and retains native continuation state, including partial progress after failure or cancellation.

`AgentSessionRegistry` holds `_Session` records containing owner, expiration and `state: SessionState`. The access path is `session.state.conversation`. Detached `SessionSnapshot` values compose native conversation state, execution records and artifacts. Presentation uses the active native execution view while a turn is running and retained native state otherwise. Observation subscriptions continue publishing complete snapshots.

## Proposed Direction

Retain one native `Conversation` as the authoritative settled continuation state. It contains messages, native conversation identity, cumulative usage, and any pending deferred-tool requests. Application ownership, expiration, artifact capabilities, published artifacts, and turn lifecycle remain application fields composed around it.

Use the native state directly where supported. Do not introduce a second custom history representation, a compatibility adapter for the old observation layout, or a permanent execution switch. Keep the application session ID distinct from native conversation identity unless a concrete benefit justifies changing that relationship.

Observation remains responsible for live execution visibility and notifications. During execution, snapshots must include the current native execution state so the UI continues to show completed messages, tool progress, and artifacts immediately. A live view and a settled baseline have different purposes; they must not become independently editable histories. At settlement, retain the native continuation state and release redundant captured history.

Successful execution provides `AgentRunResult.conversation`. Failed and cancelled turns also need to retain available native messages and usage before the next turn. The implementation must use supported native hooks or exception state to settle those paths; saving only successful results would regress current behavior. A failure before native execution starts must leave the previous continuation state intact.

The full application record contains more than the native `Conversation`. Serializing the native value alone will not preserve our complete UI session, artifacts, ownership, or lifecycle records.

## Scope Boundaries

Included in the proposed slice:

- A single native settled conversation state with application-owned session fields around it.
- Clear separation between retained continuation state and live observation.
- Initial context carried into native history with its existing hidden-origin metadata.
- Preservation of partial history and accepted artifacts after failure or cancellation.
- Detached reads and snapshots that cannot mutate retained native state.
- Focused validation that native state can be serialized and reloaded using `ConversationTypeAdapter`, without introducing a runtime save/load cycle.

Excluded:

- Databases, file storage, repositories with speculative multiple backends, or deployment changes.
- Sessions surviving restarts, refresh recovery, conversation listing, or new HTTP endpoints.
- Pydantic AI Harness, `StepPersistence`, durable execution, replay, or cross-conversation memory.
- UI adapters, monitoring integration, or new approval workflows. The exhaustion error is delivered through the backend/frontend contract and existing error UI.
- Other changes to user-visible presentation, session ownership, expiration, admission, or observation reconnect behavior beyond the agreed exhaustion handling.

## Integration Impact

| Area | Intended responsibility |
| --- | --- |
| `session_state.py` | Own the native settled conversation and application turn/artifact state; settle all execution outcomes. |
| `turns.py` | Invoke the agent with the chosen native continuation and budget semantics. |
| `observation.py` | Expose live native execution state and started-tool information; cease being the home of settled conversation history. |
| `sessions.py` | Keep owner-scoped in-memory storage, expiration, detached snapshots, and subscriptions. |
| `presentation.py` | Read native messages from the explicit session execution view rather than discover retained history through old turn captures. |
| `runner.py`, HTTP, frontend | Preserve existing submission, background execution, and complete-snapshot behavior. |

The application retains a native `Conversation`; internal session snapshots compose it with turn and artifact state. Only active turns retain a `TurnObservation`. `SessionSnapshot.messages` selects the active native execution view, falling back to retained native state during setup.

The application naming reserves `Conversation` for Pydantic AI. Application ownership uses `SessionState`, `SessionArtifact`, `SessionBusyError` and `TurnExecution`, with `turn_executions` on state and internal snapshots. The owning module is `session_state.py`; the HTTP presentation contract remains unchanged by this rename.

## Usage and Limits

The current application starts a fresh usage budget for each turn. Passing native `conversation=` also carries its usage forward, so applying the same absolute limits would turn per-turn limits into conversation-wide limits.

Agreed: preserve the existing per-turn execution budgets. These remain the primary execution guardrails. Retain cumulative native accounting without allowing earlier turns to consume a later turn's individual allowance. Translate per-turn allowances into cumulative native thresholds, including caller-supplied request, tool, token and cost limits. Preserve per-request token settings unchanged. Do not reset or discard cumulative usage just to make existing constants work.

Agreed: add a separate conversation-wide limit alongside per-turn limits. The cap is 50 model requests and 40 successful tool calls. History remains readable, submissions are disabled, and the existing error presentation shows `Conversation limit reached`. Configure it separately from per-turn budgets rather than implicitly reusing their thresholds. Every turn must respect both its own allowance and the remaining conversation-wide budget.

## Review Criteria

The cutover should demonstrate that multi-turn context and hidden initial context survive; partial output and artifacts remain visible after failure; pre-execution failures preserve prior state; cancellation retains truthful outcomes; and tool activity remains visible during execution. Snapshot mutation must not affect stored state. A serialization round trip must preserve native conversation fields and application JSON metadata used by presentation.

Budget tests should distinguish per-turn limits from cumulative accounting and verify that the separate conversation-wide limit applies across turns. Both configured Kochwiki and the deterministic demo must keep using the same session boundary. If budget exhaustion requires a public contract change, deliver it together with frontend handling rather than adding a compatibility layer.

## Delivery Decisions

- Continue through native `conversation=` and retain `AgentRunResult.conversation` on success. Preserve cumulative usage rather than resetting it between turns.
- Derive absolute native thresholds from usage at admission plus the per-turn allowance, bounded by the separate conversation caps. Native limit methods enforce the budget; a small subclass identifies conversation exhaustion distinctly.
- Reject oversized parallel batches before execution and close further admission. Successful execution exactly at a cap can complete its final answer; subsequent submissions are rejected without creating a turn.
- Publish a typed session error in snapshots and a `409 conversation_limit_reached` admission error. The existing frontend error status shows `Conversation limit reached` and disables submission while reads and observation remain available.
- Capture native live messages and usage through existing hooks, detach them on capture exit, and settle failure/cancellation from that capture. A setup failure before capture leaves prior native state unchanged. Release observations at settlement rather than retaining successive cumulative histories.

## Validation

Backend coverage includes continuation, partial failures and cancellation, initial-context metadata, active and settled snapshot isolation, native serialization, separate per-turn and conversation budgets, caller token/cost allowances, exact tool-cap completion, oversized parallel batches, and HTTP read/observe access after exhaustion. The full backend suite passes (208 tests). Frontend formatting, lint, tooling tests (13), app tests (5), chat UI tests (131), and generated-contract checks pass.

No database, runtime serialization cycle, framework upgrade, durable execution, or restart recovery was added.

## References

- [Pydantic AI persistence](https://pydantic.dev/docs/ai/core-concepts/persistence/): native `Conversation`, serialization, and the distinction between conversation storage and checkpointing.

- Installed `pydantic-ai-slim[openai,mcp]==2.58.0`: `Conversation`, `ConversationTypeAdapter`, and `AgentRunResult.conversation` are available locally. This slice does not require a framework upgrade.
