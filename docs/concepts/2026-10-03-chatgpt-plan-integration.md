# ChatGPT Plan Integration

## Status

Concept development. The backend ordered-history foundation is implemented; streaming, explicit retry, and subscription integration remain planned. Subscription-backed inference is committed planned work in [the planning initiative](../../../plan/Initiatives/ChatGPT%20Plan%20Integration.md); it is not implemented. The agreed initial deployment supports multiple users, each optionally connecting their own ChatGPT plan. The configured API key is the baseline for users without a connected plan. AI Service retains per-user credentials and refreshes them automatically so routine application use requires no repeated ChatGPT login. Other recommendations below remain tentative unless already required by that initiative.

## Context

AI Service uses its configured API key as the baseline for eligible Kochwiki and universal-agent inference when the user has not connected a ChatGPT plan. Offer plan connection to reduce reliance on that baseline, and prefer the user's connected plan for eligible requests. Domain services retain authorization, validation, proposal persistence, and explicit saving. The private, non-commercial deployment's eligibility remains the initiative's planning assumption, not a confirmed determination.

This document owns service-level concept decisions. The central initiative remains authoritative for cross-project intent. Official preview documentation was checked on 2026-10-03; requirements need another check before implementation.

The API-key baseline and multiple-user initial scope are subsequent user decisions that refine the initiative's description of API-key access as an explicit alternative. This concept records the new direction; the central initiative has not yet been synchronized.

## Current Implementation

- `backend/app/agents/wiring.py` creates a process-wide API-key client and fixed-model Kochwiki agent at startup. Missing an API key currently makes that agent unavailable. There is no universal model-backed configuration or provider connection lifecycle.
- `backend/app/models/openai_agentic_generation.py` already uses Responses, explicit input history, instructions, and `store=False`. It does not stream, sends `max_output_tokens`, and supplies ordinary function tools. Subscription access requires different request construction and supported tool packaging.
- The shared session lifecycle retains an ordered, append-only history of messages, provider continuation items, tool calls, execution outcomes, accepted artifact records, and terminal state. `backend/app/sessions/tool_turns.py` records calls before execution and results when returned. Later ordinary model turns replay that history without invoking recorded tools, including service-generated reports for calls that never started or have an unknown outcome.
- The session store retains history and artifacts in process memory for 90 minutes. A completed tool's validated artifact survives later generation failure or cancellation; candidates not returned or accepted leave no session artifact state. Active-turn artifacts remain hidden until termination, and retained artifacts consume session capacity. Failed-turn artifacts are retrievable through backend session reads; their frontend display remains deferred. Turn failure does not roll back domain work already performed by tools.
- The HTTP API returns completed turns. The frontend transport expects one JSON response and has no event stream. The shared UI must gain observable tool activity as well as incremental text.

## Proposed Direction

### Prerequisites and Starting Point

The ordered-history foundation is delivered through the existing API-key mode. The next foundation work remains streaming and deliberate recovery before ChatGPT connection, subscription routing, and the shared recovery dialog; OAuth setup need not block that development. This is conceptual dependency ordering, not an implementation specification.

| Foundation | Why it is needed | Evidence that it is ready |
| --- | --- | --- |
| Explicit turn lifecycle and retained execution context | Streaming and retry require an authoritative distinction between running, completed, failed, and uncertain work. Subsequent turns need prior tool calls and results. | Implemented in the backend: multi-turn API-key conversations replay required context, actual returned outcomes, and explicit reports for unresolved calls; completed artifacts survive later failure. |
| Streaming through provider, runtime, HTTP, controller, and UI | Users need incremental text and observable tool activity before completion. Internal provider streaming alone is insufficient. | An API-key conversation displays text and distinct tool preparation/execution/outcome entries live through the real gateway. |
| Failure reconciliation and deliberate retry | A disconnected UI must not trigger duplicate execution; a confirmed failed turn must permit an explicit retry without another user-message append. | Connection loss is reconciled; retry after a confirmed failure preserves the message and accounts for completed or uncertain tool actions. |
| Verified application identity and ownership | Multiple users need isolated conversations and provider connections. | AI Service validates the caller and rejects another user's session/connection access. Required before exposing per-user plan connection, but not a blocker for isolated foundation development. |
| Provider selection at safe turn boundaries | The recovery dialog must be able to change billing mode without changing domain behavior or losing conversation context. | Provider/model resolution is independent of agent configuration; an explicit change applies to the next eligible attempt without resubmitting in-flight work. |

The delivered slice establishes turn associations, terminal states, and retained model/execution context across ordinary turns. Settle attempt identity and the display-event boundary for streaming and explicit retry next. Then make one API-key turn observable through the whole stack, including a tool call and a failure, before attaching subscription recovery to it. These foundations should remain useful even for users who never connect a plan.

Application authentication can be worked out alongside this foundation, but must be established before real users can manage credentials or access each other's isolated resources. ChatGPT provider authorization does not supply the application's identity boundary.

Later subscription work adds persistent per-user credentials, initial authorization for the LAN deployment, the subscription-compatible adapter and model catalog, provider selection, and the shared recovery dialog. The current concept does not yet choose the identity provider, initial login helper, event transport, credential store, or retry execution strategy.

### Foundation Decisions to Resolve Next

The first bounded slice is implemented as [Ordered Conversation History and Retained Tool Outcomes](../specs/2026-10-03-ordered-conversation-history.md). It provides one authoritative ordered, append-only session history of messages, model continuation items, tool calls, outcomes, accepted artifact records, and terminal state. Record calls before execution, independently of results; consume history without re-executing it. Provider continuation items are model response context, never credentials. Artifact records reference immutable artifacts in a session-owned map and link producing calls, preserving placement for later UI visualization. Tools return validated candidates; orchestration assigns identity and atomically stores the artifact alongside its result and history reference, without staging storage. History determines ordering and publication; the map holds content. A subsequent non-streaming UI slice now displays ordered tool rows, artifacts (including failed-turn survivors), and failure markers. Calls use one shared tool icon and safe outcome statuses; raw arguments, results, and reasoning remain hidden. Streaming, per-tool icons, and expandable tool details remain deferred.

A validated artifact from a successfully completed artifact-producing tool survives later generation failure; candidates not returned or accepted leave no artifact state. This replaces blanket failed-turn artifact removal. The delivered first slice is backend-only: surviving artifacts are retrievable from session reads, while their failed-turn UI display and tool activity visualization are deferred. Replay all recorded tool calls from failed turns on later ordinary messages, including unresolved calls. Supply actual returned results where available; otherwise supply an explicitly service-generated report distinguishing execution never started from execution started with an unknown outcome. Unknown-outcome reports disclose possible completion and advise investigation before repeating a mutation. These reports are distinct from tool-returned results. Retention guides the model toward finishing completed work but does not itself guarantee duplicate-mutation prevention on a later retry.

Prefer a server-owned turn lifecycle with ordered events and a readable authoritative snapshot. A lost stream should lead to reconciliation; it must not be treated as proof that execution stopped. Whether an explicit cancellation stops remaining work is a separate unresolved choice.

A user message should stay one logical message across retries. Distinguish an attempt to answer it from the message itself so failed partial output and tool outcomes do not merge into a successful response or disappear. The relationship between logical turn and attempt identifiers belongs in the specification.

Retain model history, execution outcomes, and safe UI activity as separate views of the same work. Safe activity summaries are not sufficient model context, and raw tool payloads are not automatically suitable UI events. Keep the existing ephemeral conversation lifetime; durable chat storage is not a prerequisite.

Retry cannot universally promise exactly-once domain execution from a local record alone. If a tool's outcome is uncertain, safe retry may require domain-supported idempotency or status lookup; otherwise surface the uncertainty rather than repeat a mutation. Read-only and state-changing tools may need different replay treatment even though the plan recovery dialog is shared.

Check event validation and contract generation across backend and frontend, as well as proxy buffering and host embedding paths, when defining the streaming boundary. These are integration requirements, not authorization to change build or deployment configuration now.

### Default Routing and Connection Offer

At creation of a model-backed conversation, resolve the user's provider route on the server:

| Connection state | Route for eligible inference | User experience |
| --- | --- | --- |
| No ChatGPT plan has been connected | Configured API key | Conversation is usable immediately; offer optional plan connection. |
| Connected plan with valid or refreshable credentials | User's ChatGPT plan | Prefer plan inference and refresh credentials automatically. |
| Previously connected plan encounters an access or usage failure during refresh or inference | Stop the affected operation; no automatic paid switch | Show the shared recovery dialog asking whether to switch to the API key; retry remains a separate user action. |

All three rows are agreed direction. Not having a current access token because it needs routine refresh does not make a user unconnected. A failed plan connection also remains distinct from having never connected a plan, until the user explicitly selects API-key usage.

Identify API-key mode as using the deployment's configured API billing, and identify plan mode as using the connected account's allowance. The connection prompt should be optional and should not block API-key conversations. Only offer baseline access to callers permitted to use the application; lack of a plan connection does not grant application access.

Keep provider routing independent of agent/domain configuration. Connecting a plan affects newly created conversations under the tentative conversation binding rule below; it does not silently change an active API-key conversation. Explicitly disconnecting a plan should present the resulting API-key baseline before future conversations use it. The exact prompt placement and handling of existing conversations remain open.

### Provider Credential Ownership

Keep ChatGPT connection management in AI Service, separate from application login and domain payloads. Kochwiki and the universal-agent host may expose a connection entry point and sanitized status, but never handle provider tokens.

Resolve a permitted connection on behalf of the application user before inference. Bind the conversation to its owner, selected provider connection when applicable, provider mode, and model. Token refresh preserves that binding. An explicitly accepted switch from plan access to API-key usage changes the user's selected billing mode and permits retry within the existing conversation; a new conversation is not required. Apply the change only at a safe turn boundary, without migrating or resubmitting an in-flight request. Switching ChatGPT account or workspace remains a tentative new-conversation requirement. Do not silently redirect an existing conversation to another account or paid mode.

The agreed MVP supports multiple users with separate application-managed connections. Each user authorizes access to their own ChatGPT plan initially; AI Service protects and persists the resulting credentials and refreshes them without further interaction during routine use, including after application restarts. Do not depend on an existing Codex installation's credentials or ask users to supply access tokens for each launch. Revoked access, expired or invalid refresh credentials, or changed consent can still require explicit reconnection.

Verified application identity and server-side connection ownership enforcement are prerequisites for the initial release, consistent with DEC-002. A browser-selected user or caller-supplied connection ID does not establish ownership. Bind each provider registration to the authenticated application identity, keeping application identity separate from the validated ChatGPT account/workspace identity. Never select another user's plan as a fallback. Registration/import, status, disconnect, model discovery, conversations, and refresh handling must respect that ownership boundary.

The configured API key belongs to the deployment and remains backend-only. Every authenticated application user is allowed to use its shared API budget in the initial release, without separate administrator approval or a per-user budget entitlement. Users without a connected plan use this baseline automatically. Application authentication and existing domain authorization still apply; this decision does not grant anonymous access or broader domain permissions. Per-user spending controls are outside the initial scope. Existing bounded turn and tool execution limits remain applicable.

### Remote Deployment Connection Flow

The agreed deployment is a server in the local network, accessed by users from browsers on other computers. Treat it as remote for OAuth callback handling. The documented open-source flow uses a loopback callback on the computer running the browser. A LAN AI Service URL is not a substitute for that callback.

Recommended candidate: complete registration and OAuth through an AI Service local helper, then securely import the selected protected registration into the server. Preserve the server's stable host ID and let the server exclusively own subsequent refreshes. Reconnection repeats an explicit local authorization/import flow. Do not keep refreshing the same transferred credential session independently on both machines.

The helper is only for initial connection and exceptional reconnection; it is not required while using the application. Prefer an application-managed setup command that handles authorization and secure transfer together, rather than asking users to copy raw tokens. Import must bind the registration to the authenticated application user and verify the provider identity and consent; users should not need server administration or shared SSH access. The helper's secure handoff and user experience remain unresolved recommendations.

Keep credentials in backend-only persistent storage on the LAN server. If the service is containerized, that storage must survive container replacement and image upgrades. Keep the server host identity stable across those operations. The storage mechanism and secure transfer method remain to be selected; no deployment configuration changes are implied by this concept update.

Persist the issued registration, validated account identity, granted scopes, expiry, and rotating credentials separately from ephemeral conversations. Serialize refresh operations for each connection and replace refreshed credentials atomically. Distinguish local disconnect, upstream revocation, and reconnect-required states. The preview does not yet provide host-specific usage attribution or revocation for transferred sessions.

### Adapter and Model Selection

Use the public Responses endpoint with OAuth bearer credentials. Keep subscription-specific request construction behind the model provider boundary; reuse orchestration and domain tools. A separate subscription adapter is the tentative preference over conditionals spread across the runtime.

Discover models using the selected account's catalog, display the provided names, and send the selected slug. Never assume the API-key catalog or fixed Kochwiki model is available to this account. Decide later whether the initial UI offers a model picker or uses an explicitly configured account-available default.

Set `stream=true` and `store=false`, send required history in an input array, and use instructions or developer guidance. Omit unsupported fields, including the current output-token limit. Adapt function tools into the documented namespace or additional-tool format while preserving stable runtime call identities. Domain MCP discovery and execution remain local to AI Service.

Continue enforcing service limits on provider responses, tool attempts, input/history size, time, and accepted output. Removing an unsupported provider parameter must not remove bounded orchestration. Exact limits and event schemas belong in the later specification.

### Streaming and Tool Transparency

Expose a provider-neutral turn event contract owned by AI Service. SSE over the turn request is a candidate transport; its exact lifecycle remains undecided. Update the backend, generated contract, conversation transport/controller, and shared UI together. Keep the `/ui` entry point independent of network access.

Events should cover turn start, provisional text, tool preparation, validated execution start, tool outcomes, and terminal turn state. Give each event stable turn/call identity and ordering so repeated calls remain distinct and future parallel calls remain possible. Parallel execution is not itself required for this provider integration.

Treat streamed argument fragments as preparation. Execute a tool only once complete arguments have been received and validated. Runtime execution determines completion or failure; a provider function-call event alone cannot establish the tool's execution outcome. Use tool-owned labels and safe input/result summaries, excluding credentials, sensitive payload fields, and private model reasoning.

Keep streamed text provisional until successful turn completion. Provider success requires its completed event; an interrupted, incomplete, or failed stream is a distinct failure even after text has appeared. A whole agent turn succeeds only after orchestration and artifact acceptance also complete.

### History, Failure, and Recovery

Retain model context separately from display history and safe activity summaries. Preserve required provider output items, complete tool calls, and their results across turns within the existing ephemeral session lifetime. Durable conversation storage is not required; durable credentials are.

Retain an authoritative record of tool execution outcomes when a provider response fails after a tool ran. Replay both completed and unresolved calls, using clearly identified service execution reports for missing results rather than omitting the exchange or fabricating a tool return. Preserve confirmed results alongside uncertain ones. Completed, validated tool-produced artifacts survive later generation failure, while candidates not returned or accepted leave no artifact state. Domain proposals remain independent of presentation artifacts. Never imply a turn failure rolled back domain work, and never automatically repeat a potentially state-changing tool because the UI connection was lost.

Recommended candidate: UI transport loss triggers session/turn reconciliation, rather than silently replaying the turn. Decide whether explicit cancellation stops work and what terminal outcomes it records separately from disconnect behavior. Cancellation cannot undo a tool already completed.

### Shared Plan Recovery Dialog

Plan access or usage failures detected during token refresh and inference use the same user-facing recovery mechanism. Preserve the actual reason internally and show a safe explanation in one shared dialog asking whether the user wants to switch to the deployment's shared API key. The detection point does not change the user's decision or the billing-switch behavior.

- A refresh failure that prevents plan use stops the affected operation and surfaces the dialog to the owning user. If detected in background refresh while no UI is connected, retain the recovery state and surface it when that user next interacts; browser presence is not required for background refresh.
- An inference failure, including one received after streaming begins, fails the turn and opens the same dialog. Keep any streamed text visibly incomplete and retain the failed user message for retry.
- Accepting switches the user's selected billing mode to API-key usage. Do not automatically resend the request or append a duplicate user message. The user explicitly retries the failed message within the existing conversation.
- Declining leaves plan mode selected and does not incur API-key charges. Reconnection or a later retry can remain available as appropriate to the reported cause.

Error classification still determines credential lifecycle: retain credentials for temporary failures, clear unusable tokens for confirmed terminal refresh errors, and keep subscription-limit state separate from token expiry. Unsupported requests, configuration defects, domain/tool errors, and unrelated transport failures remain ordinary errors rather than reasons to change billing.

Retry must account for tool executions that completed before the failure, preserving their outcomes and avoiding duplicate state-changing actions. Switching providers does not roll back domain work. The frontend can retry turn generation after an uncertain request, but the backend caches confirmed failed terminal turns and has no explicit operation to start a new attempt for that failed message. Deliberate retry and replayable cross-provider context therefore require changes to the conversation lifecycle. Model selection must also be validated for API-key mode rather than assuming a plan-only model is available there; the concrete retry and model-mapping contract remains specification work.

Preserve the app-owned error envelope before streaming begins; after headers are sent, use a typed terminal error event. Both feed the same recovery state and dialog. Repeated reports of the same issue should update that state rather than open competing dialogs. Exhausted subscription access must never trigger automatic paid API-key fallback.

## Scope Boundaries

- Eligible Responses inference and client-executed tools are in scope. ChatGPT memories and conversation history are not.
- Embeddings, image generation, audio, and other unsupported hosted tools retain separate capability and billing paths. Web Search support needs independent verification for the selected model/account.
- No broad domain, filesystem, shell, or network access is introduced by provider authentication.
- The universal agent reuses this provider/runtime work; weather tooling is not a prerequisite.
- This concept does not authorize code changes, deployment/tooling changes, or a general authentication redesign.

## Open Questions

The immediate discussion concerns the foundation: event transport and lifecycle, disconnect/cancellation behavior, retained failed-attempt context and artifacts, and safe retry after completed or uncertain tools. Identity integration must also be resolved before per-user credentials are exposed. The remaining login and subscription UI questions follow those foundations.

1. Which application authentication/session flow identifies users to AI Service in keeping with DEC-002? Shared API-key access is agreed for every authenticated application user; ChatGPT provider consent does not authenticate callers of the domain APIs.
2. For the confirmed LAN server deployment, is an application-managed local setup command acceptable for initial connection and exceptional reconnection? What server/container topology, protected credential store, and secure transfer method fit the deployment?
3. Should connection management initially be an operator workflow, a shared AI Service screen linked from hosts, or an embedded host settings component?
4. Should a model be selected per new conversation or supplied by configuration after account-catalog validation?
5. Does a UI disconnect leave the turn running for reconciliation? Is explicit cancellation part of the first streaming release?
6. How will explicit recovery handle unresolved calls and possible duplicate domain actions, and how should later expandable tool details work? Ordered tool activity and retained failed-turn artifacts are now displayed without streaming. Backend retention and replay boundaries for the first slice are settled in its specification.
7. Where should the optional plan-connection prompt, shared recovery dialog, and provider/billing indicator appear? How are explicit retry and model selection represented when switching the existing conversation to API-key usage?

## Risks

The agreed multiple-user design requires verified application identity and credential isolation from the start. The current process-wide API-key client may serve the baseline, but subscription requests require per-user credential resolution. The deployment owner bears API costs for all authenticated users using the baseline; the initial release deliberately has no per-user spending controls.

Credential persistence and ephemeral conversation state have different lifetimes. Disconnect, account switching, refresh races, and in-flight requests must not accidentally cross connections.

Streaming changes completion and recovery semantics across the whole UI contract. Proxy buffering and host transport paths must be checked during implementation; receiving a provider stream internally is insufficient.

## Sources

- [Registration and sign-in](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)
- [Self-hosted VMs](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms)
- [Models and inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)
- [Preview limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)
- [Errors and recovery](https://developers.openai.com/siwc/token-sharing-open-source/errors-and-recovery)

## Summary

Allow every authenticated application user to use the shared API-key baseline without separate administrator approval. Offer optional plan connection and prefer each user's connected plan for eligible new conversations. Refresh and inference failures share one recovery dialog: an explicit switch to API-key usage permits manual retry in the existing conversation, without automatic resubmission or duplicated tool actions. Keep credentials persistent and isolated per user on the LAN server with automatic refresh. Focus next on the reusable turn lifecycle, retained tool context, end-to-end API-key streaming, and safe retry. Establish application identity before adding per-user plan connection and recovery.
