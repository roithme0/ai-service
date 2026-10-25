# Artifacts

Artifacts are structured presentation data published by an agent within a [session](conversations.md). Presenting an artifact does not save business data.

## Glossary

| Term | Meaning |
| --- | --- |
| Capability | A consumer-advertised artifact type, usage guidance, and payload schema. It may include header guidance and a metadata schema. |
| Publication | A `present_artifact` call accepted after schema and session-capacity checks. |
| Published artifact | A retained payload with type, title, optional subtitle and metadata, artifact ID, timestamp, and native run ID. |
| Payload | Complete JSON presentation data matching the advertised schema. Renderers do not fetch missing details. |
| Metadata | Optional structured information interpreted by the consumer; it has no built-in action or rendering behavior. |
| Renderer | Consumer-selected UI that displays an artifact. Registering one does not advertise a capability to the agent. |
| JSON capability | Built-in type `json`, with payload `{ "value": <JSON value> }`. |

## Publication rules

- Capabilities are fixed at session creation, with unique type names. A model-backed session without capabilities has no artifact publication tool.
- Payload and metadata schemas use JSON Schema draft 2020-12 without external references. Metadata requires an advertised schema; omission is validated as an empty object.
- Acceptance assigns an ID and retains a detached payload before returning success to the agent. Rejection publishes nothing and becomes a failed tool result.
- A session accepts up to 100 artifacts by default. Accepted artifacts survive later turn failure or cancellation and keep consuming capacity.
- Reading history does not republish artifacts. A new publication call may still create a duplicate; there is no deduplication guarantee.

## Responsibility boundaries

MCP services own domain tools and workflow instructions. AI Service owns generic conversation and publication behavior. Consumer frontends choose supported capabilities, renderers, and domain actions.

Start with [artifact validation](../../backend/app/capabilities/agentic/artifacts.py), [UI capabilities](../../frontend/projects/chat-ui/ui/lib/artifact-capabilities.ts), and the [presentation mapper](../../frontend/projects/chat-ui/conversation/src/session-presentation.ts).
