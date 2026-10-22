# Conversations

A session connects one owner to one configured agent. The service manages execution and presentation; external MCP services own business operations.

## Glossary

| Term | Meaning |
| --- | --- |
| Agent configuration | A named application composition: `demo` or `kochwiki`. |
| Session | An expiring, owner-scoped container for conversation state, executions, and [artifacts](artifacts.md). Its ID is separate from native conversation and run IDs. |
| Owner | The `application:user` identity supplied through `X-Application-User`. Ownership checks do not authenticate the caller. |
| Conversation | Native Pydantic AI continuation state: messages, usage, and conversation identity. |
| Initial context | Caller-provided JSON object retained as model input, outside the public timeline. It is data, not agent instructions. |
| Turn | One admitted prompt execution, with status `running`, `completed`, `failed`, or `cancelled`. Its native run ID may be absent before execution starts. |
| Admission | Acceptance of a prompt for background execution. HTTP 202 does not mean the turn completed. |
| Snapshot | A complete public view of ordered prompts, execution groups, and their presentation parts. |
| Observation | An SSE subscription to snapshots; connection status is separate from execution status. |

## Session rules

- Sessions expire 90 minutes after creation; activity does not extend them. Unknown, expired, and other-owner sessions return the same not-found result.
- Only one turn may run per session. An overlapping submission is rejected without creating another execution.
- An admitted turn may finish after expiry, but expiry still prevents further reads and submissions.
- Failure or cancellation retains captured history and accepted artifacts. It does not establish whether interrupted external actions occurred.
- Conversation budget exhaustion blocks further submissions; reads and observation remain available until expiry. [Execution limits](../../backend/app/agentic/config.py) are separate from session lifetime.

## Observation and recovery

- Backend snapshots supply displayed conversation content; the frontend adds no optimistic messages.
- Disconnecting observation does not cancel a turn. The controller reconnects transient failures without resubmitting prompts.
- A missing admission response leaves submission uncertain and the draft retained. Observation recovery does not resolve that uncertainty or automatically retry submission.
- Session state is held in memory and disappears on backend restart.

Start with [session state](../../backend/app/agentic/session_state.py), [registry](../../backend/app/agentic/sessions.py), and the [frontend controller](../../frontend/projects/chat-ui/conversation/src/session-controller.ts).
