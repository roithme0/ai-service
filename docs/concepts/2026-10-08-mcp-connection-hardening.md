# MCP Connection Hardening

## Status

Evolving concept as of 2026-10-08. Slice 1, runtime-owned initial connection recovery, and slice 2, automatic catalogue refresh, are implemented. Reconnection after an established connection fails remains conditional on a small, safe extension of the same lifecycle. Slice 3, automatic server-instruction refresh alongside tools for modern MCP servers, is implemented.

Scheduled catalogue polling every five minutes is agreed for the first version. Server notifications are deferred. A fixed 30-second startup retry delay and consolidated runtime status are agreed and delivered.

## Context

`backend/app/agents/wiring.py` constructs agent-owned MCP connections from server configuration. FastAPI startup starts each `AgentRuntime`; `MCPConnection.start()` enters the SDK client, fetches all tool pages and retains server instructions. `MCPToolset` validates and maps tool names to model functions. Connections are shared across conversations, and the tool loop builds its registry and instructions once per turn.

The runtime retries recognized startup transport failures while retaining its agent and model client. After successful connection it polls tool catalogues every five minutes, including while unavailable after a catalogue failure. Tool-call exceptions become generic failures, without application-managed reconnection. Polling also retrieves fresh server instructions through modern discovery and publishes them with tools. The demo has no MCP dependency and remains independent.

## Goal

Allow a configured agent to become usable when its MCP server starts late, and keep the available tools current without restarting AI Service. Preserve conversation state, bounded tool execution and accurate failure history. Recovery remains owned by AI Service; domain services continue owning tool validation and mutations.

## Proposed Direction

### Initial Connection Retry

`AgentRuntime` owns connection coordination, retry scheduling and background SDK context ownership. `MCPConnection` performs start, tool call and close operations; it does not own retry or polling policy. The runtime begins connection attempts immediately in the background and retries recognized transient failures until successful or shutdown. The delay is 30 seconds after failed-attempt cleanup. Attempts do not overlap, and startup does not wait for the MCP server before allowing independent agents to serve requests.

Runtime status is `created`, `connecting`, `ready`, `unavailable`, `closing`, or `closed`. A separate typed issue records the failure category, affected connection where known, and retryability. Every configured MCP connection is mandatory; HTTP derives availability from `ready`. Detailed runtime diagnostics are internal, without a new status endpoint.

Connection success includes negotiation, complete catalogue discovery and validation. Do not expose a partially initialized connection. Construct a fresh SDK client for each connection attempt and close partial resources on failure; do not assume a failed SDK client can be entered again.

Separate temporary MCP unavailability from permanent runtime shutdown. Keep the configured agent, session store and model client alive during connection recovery. Missing credentials, invalid URLs and incompatible configuration remain configuration failures; repeatedly attempting an absent or malformed configuration does not repair it. Invalid catalogues should be logged distinctly from network outages and rechecked on the refresh cadence, allowing a corrected server to recover without a restart.

Keep retry and refresh intervals as positive application settings, preferably in a dedicated MCP settings module. They are service policy rather than model instructions. A fixed interval is sufficient for the current personal deployment; exponential backoff and jitter are optional future needs for larger deployments.

### Automatic Catalogue Refresh

Use scheduled polling every five minutes while connected. Always perform full discovery after connecting or reconnecting. Poll all tool pages using the SDK's explicit cache refresh or bypass mode; otherwise its default catalogue cache may hide server changes.

Build a complete candidate catalogue before publishing it. Validate model-facing names and duplicates across configured connections. Publish a validated catalogue atomically. Anything other than complete successful discovery and validation clears the affected published catalogue and marks the runtime unavailable; do not retain its previous valid catalogue as a fallback. This includes timeouts, failure on a later page and invalid tool names. Continue polling so a corrected catalogue can restore readiness without a restart. Successful deletion of every tool is a valid empty catalogue, distinct from a catalogue cleared because validation failed. Validation errors alone do not justify reconnecting a healthy transport. Collisions with session-specific local tools remain checked during turn assembly.

Each turn must capture one consistent snapshot of tools, mappings and instructions. A catalogue published during an active turn applies to subsequent turns, including those in existing sessions. Do not change the registry halfway through a model/tool loop. Concurrent sessions can therefore use different catalogue generations temporarily. A removed or changed server tool may still reject a call from an older turn; snapshotting cannot preserve the server's previous implementation.

Slice 2 originally refreshed tool definitions and generated mappings only. Slice 3 extends each polling pass to fetch fresh server instructions through modern `server/discover` before listing all tool pages. Publish instructions and tools together only after complete validation. Any failure clears both for the affected connection. Assume modern servers; legacy initialization-based instruction refresh is outside this delivery.

### Scheduled or Triggered?

| Approach | Benefit | Cost or limitation |
| --- | --- | --- |
| Scheduled polling | Works without server change notifications; also detects idle discovery failures | Changes become visible after the polling interval; recurring discovery traffic |
| Server-triggered refresh | Faster updates with little steady discovery traffic | Requires server capability support and notification/subscription handling for the negotiated protocol |
| Notifications plus polling | Fast updates with eventual refresh after missed notifications | Adds both mechanisms, including event coalescing and subscription recovery |

Polling is the chosen approach for the first delivery. Add server notifications later if update latency becomes a concrete problem. Notifications should mark the catalogue dirty and request a full refresh, rather than modifying definitions directly. Coalesce repeated triggers and serialize them with polling and connection recovery.

MCP declares tool-change support through `tools.listChanged`. The notification path differs between the handshake-era protocol and the newer subscription-based protocol. The installed SDK supports both protocol eras, so notification support needs a negotiated-version-aware design. See the official [2025-06-18 tools specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-06-18/server/tools.mdx) and [2026-07-28 tools specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/server/tools.mdx).

### Conditional Reconnection on Error

Reuse the connection retry lifecycle only for classified connection loss, such as a closed transport or invalidated MCP session. A domain `isError`, bad arguments or ordinary tool rejection must not trigger reconnect. A timeout may leave a healthy connection and an uncertain tool outcome; it is not sufficient by itself to justify retrying an operation.

Report the current call's failure or uncertain outcome through the existing history mechanism. Do not automatically repeat that tool call, restart the turn or replay earlier calls. Reconnection restores transport availability for later calls; it does not prove that the failed operation had no effect. Preserve explicit uncertainty so the model is not encouraged to repeat a mutation blindly.

Use one recovery owner per connection, with errors signalling it rather than starting competing reconnects. Prevent new calls on a connection being replaced, and allow or settle in-flight calls before closing its resources. Fully rediscover and validate tools before making a replacement connection available.

Include this feature only if SDK error classification, async context ownership and coordination with concurrent calls can be handled locally. If it requires a broad rewrite or reliable session recovery machinery, defer it explicitly and deliver initial retry plus catalogue refresh first. Its ease is not established by code inspection alone.

## Integration Impact

- `AgentRuntime` now distinguishes dependency readiness from final closure. A failed MCP attempt no longer calls the permanent runtime shutdown path. It owns the repair routine and will own future polling and reconnect coordination.
- `MCPConnection` retains start, call and close operations, with fresh clients on repeated starts. Enter and exit SDK contexts in the runtime's owning task; avoid moving task-bound cleanup between request and background tasks. Complete catalogue generations belong to slice 2.
- `MCPToolset` and turn input assembly must capture tools and matching instructions from the same generation. Across multiple connections, new turns require all configured dependencies to be ready; one failure must not close unrelated healthy connections.
- The HTTP registry retains the agent transport while unavailable. Slice 2 preserves session reads and SSE observation during a temporary outage; session creation, message appends and new turns check current readiness at admission and return the existing `503 agent_unavailable` response when unavailable. Existing history remains accessible with unchanged ownership checks, and recovery reuses the same agent and session store.
- Shutdown must stop admission and recovery scheduling, settle active turns, then close transports and the model client. Background tasks must be tracked and awaited; cancellation must interrupt retry waits and ongoing attempts.

No new public status endpoint or frontend recovery feature is proposed. The host can retry a rejected request later; an existing failed turn is not automatically resumed. Any eventual API contract change must ship with this repo's frontend contract.

## Scope Boundaries

Cover shared, server-configured MCP connections. Do not add MCP authentication, user-specific connections, resource/prompt discovery, persistent sessions, tool-call retries, mutation deduplication, rollback, or browser/SSE reconnection. Keep sequential execution of grouped model tool calls and existing turn budgets.

## Controlled Delivery Slices

Use this concept as the evolving direction. Discuss one slice's observable behavior and boundaries, record the agreed details here, implement and validate that slice, then return to discussion of the next slice. The details below are proposed until agreed; they do not authorize delivery of every slice at once.

1. **Delivered: initial startup recovery:** background connection attempts, explicit readiness and reliable shutdown. Establish the lifecycle needed by later slices without changing established connections.
2. **Delivered: scheduled catalogue refresh:** five-minute polling, complete validated updates and consistent turn snapshots. Clear catalogues after any refresh failure, mark the runtime unavailable and allow recovery through later valid discovery. Preserve history reads while blocking session creation, message appends and new turns. Bypass SDK caching explicitly.
3. **Delivered: server-instruction refresh:** modern discovery on the same connection, combined publication and clearing of tools and instructions.
4. **Conditional reconnect:** assess error classification and concurrent-call coordination using the delivered lifecycle. Implement only if the change remains narrow; otherwise record why it is deferred. Never replay a failed tool call automatically.

Server-instruction refresh is delivered separately from reconnect; modern discovery avoids replacing established connections.

### Slice 1: Initial Startup Recovery

**Status:** agreed and implemented.

The observable outcome is that AI Service starts while Kochwiki's MCP server is offline, the demo works immediately, and Kochwiki becomes usable when the MCP server later becomes available without restarting AI Service.

Delivered behavior:

- Launch the first connection attempt immediately in a tracked background owner task. Application startup does not wait for that attempt. There may consequently be a short `503 agent_unavailable` window even when the server is healthy.
- After a transient connection or discovery failure, clean up the failed attempt and wait 30 seconds before the next attempt. The delay starts after cleanup completes. Keep the existing 60-second SDK request timeout; it is not an overall deadline for paginated discovery.
- Create a fresh SDK client for each attempt. The task that owns the SDK context keeps ownership until that context closes, including after successful initialization.
- Publish readiness only after all configured connections have completed discovery and model-facing name validation. Preserve healthy initialized connections while retrying another connection; attempts for each connection do not overlap.
- Keep the configured agent and model client alive while waiting. Expose the existing unavailable response through the HTTP registry until ready. Once ready, retain the same service instance.
- Missing or invalid local configuration starts no retry task. Unsupported or duplicate discovered tool names leave the agent unavailable and produce a distinct logged validation failure. Rechecking such catalogues is deferred to slice 2 rather than treating validation errors as transient network failures.
- Shutdown stops admission, interrupts pending attempts or retry delays, settles active turns, and requests connection closure through the owner tasks before closing the model client. Cleanup is awaited; tasks cannot outlive application lifespan.

This slice does not detect or recover failures after initial readiness, poll tools, or change tool-result uncertainty semantics. Because it only handles initial connection, there are no existing sessions before readiness; preserving session reads during a later outage is introduced in slice 2. Avoid introducing new API fields or frontend recovery controls for this slice.

Acceptance evidence should cover startup returning while a connection attempt is blocked, demo availability and Kochwiki's existing 503 response, failed-attempt cleanup followed by successful recovery, no overlapping attempts, full catalogue validation before readiness, missing configuration without retries, shutdown during both an attempt and a retry wait, and normal tool execution and shutdown after recovery. Tests should control timing rather than wait 30 real seconds.

The background-first startup behavior, 30-second retry setting in `backend/app/mcp/config.py`, and deferral of invalid-catalogue recovery to slice 2 are agreed. Retry classification covers transport errors, connection/timeout failures, SDK connection-closed and request-timeout codes, and directly raised HTTP 5xx/408/429 errors, including exception groups containing only retryable failures. Unclassified initialization errors remain unavailable with a nonretryable issue; arbitrary programming errors are not retried.

Regression coverage exercises background startup, HTTP 503-to-ready recovery, independent demo availability, a fresh SDK client after failed discovery, retention of healthy dependencies, catalogue rejection, real SDK context cleanup, cancellation during discovery or retry waits, and complete configured-agent tool turns. Existing startup tests now await readiness explicitly because startup intentionally returns before remote discovery completes.

### Slice 2: Automatic Catalogue Updates

**Status:** agreed and implemented.

The runtime schedules full catalogue polling every five minutes on established connections, measured after initialization or the previous polling pass completes. Attempts do not overlap. `MCPConnection.discover()` returns a complete candidate without publishing it; its private `_discover_tools(client)` helper uses `cache_mode="bypass"` on every page and is shared with startup. `MCPToolset` retains its identity and reads the current published connection catalogues when assembling a turn. Validate complete candidates before publishing them; never expose intermediate pages.

Anything other than complete successful discovery and validation clears the affected connection's published tools and makes the entire runtime unavailable because every configured connection is mandatory. Keep unrelated healthy connection catalogues and transports. Continue polling, including after initial catalogue validation failure, and restore readiness only when every required catalogue is valid. Initial aggregate validation failure clears the initial catalogues and requires polling validation before readiness. An empty successful catalogue remains valid; readiness tracks validation success separately from tool count.

While unavailable, allow existing session history reads and SSE observation. Block new sessions, message appends and new turn starts. Already-running turns retain their captured definitions and may finish; clearing published tools does not rewrite their snapshots or replay failed calls. Server-side changes can still make their calls fail.

Slice 2 initially retained connection-negotiated instructions. Slice 3 below extends refresh to include server instructions. Generated mappings continue to follow each published tool catalogue.

Regression coverage should establish complete paginated publication, invalid-catalogue clearing and loss of readiness, recovery after a corrected catalogue, valid empty catalogues, initial validation recovery, consistent active-turn snapshots, retained session reads and observation, blocked writes and turn admission, and shutdown during polling.

Delivered regression coverage exercises those boundaries with controlled polling intervals and real SDK contexts. Shutdown settles active turns before cancelling pending discovery and closing SDK contexts in their owning task. No new public response fields or frontend recovery controls are introduced.

### Slice 3: Server Instructions Alongside Tools

**Status:** agreed and implemented.

Assume modern MCP servers for this delivery. The running configured KochWiki endpoint was verified to negotiate `2026-07-28` and return instructions through a fresh `server/discover` on its existing connection. Legacy instruction refresh and connection replacement are out of scope.

Keep the existing five-minute schedule and runtime ownership. `MCPConnection.discover()` returns a typed candidate containing complete tools and optional instructions without publishing either. Send a fresh discovery request at the connected protocol version through the SDK's `send_discover()` method; `discover()` and `client.instructions` retain cached negotiation results and cannot provide freshness. Validate the discovery result and require continued support for the connected version. Do not adopt new negotiation state or change capabilities and protocol version underneath active calls.

Fetch metadata first, then all uncached tool pages, and validate model-facing names before publishing both fields together without an intervening await. Missing or empty instructions are valid and remove previous guidance. A timeout, malformed metadata, incompatible version, pagination failure or invalid catalogue clears both published tools and instructions for the affected connection and makes the runtime unavailable. Initial aggregate catalogue validation failure also clears both. Continue polling for recovery while retaining healthy connections and session history.

Active turns retain their captured instructions, definitions and mappings; subsequent turns in existing sessions receive the new combined update. Publication is atomic locally, but the protocol does not provide a common revision across metadata and paginated tools. A server changing during discovery can therefore produce a mixed server revision despite complete successful responses. No stronger server snapshot guarantee is claimed.

Legacy connections cannot perform this refresh and fail it explicitly; no fallback retaining stale instructions is provided. Reconnection remains deferred. Regression coverage exercises updated and removed instructions, malformed metadata and timeout clearing, incompatible protocol versions, later-page failure without partial publication, recovery, active-turn snapshots and shutdown under the existing owner task.

## Risks and Validation

Background discovery must not block tool calls behind an agent-wide lock. Connection replacement must not close a transport underneath another session's active invocation. Polling detects some idle outages but is not a complete health guarantee, and refresh traffic grows with the number of backend processes and configured connections.

Meaningful regression coverage should establish late-server recovery, independent demo availability, cancellation during retry, clean shutdown, complete paginated refresh, invalid-update clearing and recovery, consistent active-turn snapshots and session retention across outages. Conditional reconnect needs concurrent-call coverage and proof that a failed mutation is never automatically invoked again.

## Open Questions

- Verify SDK exception classification and task ownership before deciding whether reconnect meets the user's simplicity condition.
