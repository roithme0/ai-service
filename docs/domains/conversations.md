# Conversations

A session connects one owner to one configured agent. The service manages execution and presentation; external MCP services own business operations.

## Glossary

| Term | Meaning |
| --- | --- |
| Agent configuration | A named application composition: `demo` or `kochwiki`. |
| Session | An expiring, owner-scoped container for conversation state, executions, and [artifacts](artifacts.md). Its ID is separate from native conversation and run IDs. |
| Owner | The exact issuer/subject pair supplied through `X-Application-User`. Ownership checks do not authenticate the caller. |
| Conversation | Native Pydantic AI continuation state: messages, usage, and conversation identity. |
| Initial context | Caller-provided JSON object retained as model input, outside the public timeline. It is data, not agent instructions. |
| Turn | One admitted prompt execution, with status `running`, `completed`, `failed`, or `cancelled`. Its native run ID may be absent before execution starts. |
| Admission | Acceptance of a prompt for background execution. HTTP 202 does not mean the turn completed. |
| Snapshot | A complete public view of ordered prompts, execution groups, and their presentation parts. |
| Observation | An SSE subscription to snapshots; connection status is separate from execution status. |

## Session rules

- Every request supplies exactly one `X-Application-User: encodeURIComponent(issuer):encodeURIComponent(subject)` assertion. Both components must be nonempty, correctly percent-encoded UTF-8. Ownership compares decoded pairs, preserving exact issuer spelling and decoding once; equivalent encodings identify the same owner.
- Kochwiki MCP requests carry the session owner's assertion in the same header, encoded independently for each background turn. Identity is transport metadata and is not added to model context or tool arguments. Kochwiki resolves the pair to its own user ID for proposal ownership checks.
- This is a temporary, unverified assertion flow. Neither the session API nor this MCP forwarding authenticates the caller; authenticated delegation remains future work.
- Sessions expire 90 minutes after creation; activity does not extend them. Unknown, expired, and other-owner sessions return the same not-found result.
- Only one turn may run per session. An overlapping submission is rejected without creating another execution.
- An admitted turn may finish after expiry, but expiry still prevents further reads and submissions.
- Failure or cancellation retains captured history and accepted artifacts. It does not establish whether interrupted external actions occurred.
- Conversation budget exhaustion blocks further submissions; reads and observation remain available until expiry. [Execution limits](../../backend/app/capabilities/conversations/config.py) are separate from session lifetime.

## Observation and recovery

- Backend snapshots supply displayed conversation content; the frontend adds no optimistic messages.
- Disconnecting observation does not cancel a turn. The controller reconnects transient failures without resubmitting prompts.
- A missing admission response leaves submission uncertain and the draft retained. Observation recovery does not resolve that uncertainty or automatically retry submission.
- Session state is held in memory and disappears on backend restart.

## Usage accounting

Session and turn usage follow [Pydantic AI's usage semantics](https://pydantic.dev/docs/ai/api/pydantic-ai/usage/). Repeated presentation groups for one turn carry the same full turn usage; use session usage for conversation totals. Estimated USD totals can omit unpriced requests; they are not billing records.

Start with [session state](../../backend/app/capabilities/conversations/session_state.py), [registry](../../backend/app/capabilities/conversations/sessions.py), and the [frontend controller](../../frontend/projects/chat-ui/conversation/src/session-controller.ts).
