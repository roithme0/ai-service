# ChatGPT Plan Integration

## Status

Concept development. The ordered-history and end-to-end streaming foundations are implemented. Failure reconciliation and deliberate retry are deferred for now; application identity and ownership is the next prerequisite to discuss. Subscription integration remains planned. Subscription-backed inference is committed planned work in [the planning initiative](../../../plan/Initiatives/ChatGPT%20Plan%20Integration.md); it is not implemented. The agreed initial deployment supports multiple users, each optionally connecting their own ChatGPT plan. The configured API key is the baseline for users without a connected plan. The planned connection lifecycle retains per-user credentials and refreshes them automatically so routine application use requires no repeated ChatGPT login. Other recommendations below remain tentative unless already required by that initiative.

## Context

AI Service uses its configured API key as the baseline for eligible Kochwiki and universal-agent inference when the user has not connected a ChatGPT plan. Offer plan connection to reduce reliance on that baseline, and prefer the user's connected plan for eligible requests. Domain services retain authorization, validation, proposal persistence, and explicit saving. The private, non-commercial deployment's eligibility remains the initiative's planning assumption, not a confirmed determination.

This document owns service-level concept decisions. The central initiative remains authoritative for cross-project intent. Official preview documentation was checked on 2026-10-03; requirements need another check before implementation.

The API-key baseline, multiple-user initial scope, and trusted-LAN identity mode are subsequent user decisions refining the initiative. This concept records the new direction; the central initiative has not yet been synchronized. The trusted-LAN exception supersedes this concept's previous requirement for verified application login before exposing per-user connections; alignment with DEC-002 remains cross-project follow-up.

## Current Implementation

- `backend/app/agents/wiring.py` creates a process-wide API-key client and fixed-model Kochwiki agent at startup. Missing an API key currently makes that agent unavailable. There is no universal model-backed configuration or provider connection lifecycle.
- `backend/app/models/openai_agentic_generation.py` uses streamed Responses, explicit input history, instructions, and `store=False`. It sends `max_output_tokens` and supplies ordinary function tools. Subscription access still requires different request construction and supported tool packaging.
- The shared session lifecycle retains an ordered, append-only history of messages, provider continuation items, tool calls, execution outcomes, accepted artifact records, and terminal state. `backend/app/sessions/tool_turns.py` records calls before execution and results when returned. Later ordinary model turns replay that history without invoking recorded tools, including service-generated reports for calls that never started or have an unknown outcome.
- The session store retains history and artifacts in process memory for 90 minutes. A completed tool's validated artifact survives later generation failure or cancellation; candidates not returned or accepted leave no session artifact state. Accepted artifacts are available during active turns through safe snapshots and streaming, and retained artifacts consume session capacity. The frontend displays ordered tool activity and artifacts, including failed-turn survivors. Turn failure does not roll back domain work already performed by tools.
- The HTTP API admits backend-owned turns with HTTP 202 and exposes a separate SSE observer. Typed snapshots, item upserts, closing notifications, and terminal events reach the conversation controller and shared UI. Streaming publishes complete messages and tool preparation/execution/outcome updates; token-by-token text and argument fragments are not part of the delivered UI contract. Work continues when a request or observer disconnects. Lost observation leaves the outcome unknown and submission disabled; reconnect, refresh recovery, deliberate retry, and user-controlled cancellation are not implemented.
- The conversation HTTP boundary requires `X-Application-User` and validates its `source:id` structure without restricting prefixes or looking up users. The shared transport sends the host-supplied identity on every request, including SSE; the demo supplies `demo:default`. This identity is trusted without authentication. Per-user session ownership and provider connections are not implemented.

## Proposed Direction

### Prerequisites and Starting Point

The ordered-history and streaming foundations are delivered through the existing API-key mode. Failure reconciliation and deliberate retry are deferred for now. Proceed next with discussion of application identity and ownership; this work does not depend on completing retry first. Deferral does not remove safe retry as a requirement for the later subscription recovery dialog. This is conceptual dependency ordering, not an implementation specification.

| Foundation | Why it is needed | Evidence that it is ready |
| --- | --- | --- |
| Explicit turn lifecycle and retained execution context | Streaming and retry require an authoritative distinction between running, completed, failed, and uncertain work. Subsequent turns need prior tool calls and results. | Implemented in the backend: multi-turn API-key conversations replay required context, actual returned outcomes, and explicit reports for unresolved calls; completed artifacts survive later failure. |
| Streaming through provider, runtime, HTTP, controller, and UI | Users need text and observable tool activity before completion. Internal provider streaming alone is insufficient. | Implemented: complete messages, tool preparation/execution/outcomes, and accepted artifacts stream through backend-owned turns and a separate SSE observer to the UI. |
| Failure reconciliation and deliberate retry | A disconnected UI must not trigger duplicate execution; a confirmed failed turn must permit an explicit retry without another user-message append. | Deferred for now. Future readiness requires connection-loss reconciliation and explicit retry that preserves the message and accounts for completed or uncertain tool actions. |
| Application identity and ownership | Multiple users need conversations and provider connections assigned to the correct application user. | Next discussion. Initial readiness requires a stable selected-user identity and ownership checks against it in trusted-LAN mode. Verified SSO login is deferred and does not block exposing connections in this mode. |
| Provider selection at safe turn boundaries | The recovery dialog must be able to change billing mode without changing domain behavior or losing conversation context. | Provider/model resolution is independent of agent configuration; an explicit change applies to the next eligible attempt without resubmitting in-flight work. |

The delivered foundations establish turn associations, terminal states, retained model/execution context, and live safe timeline updates. They remain useful even for users who never connect a plan. Attempt identity and safe explicit retry remain future recovery work.

Application identity and ownership are the next focus. Initially, AI Service accepts the selected Kochwiki user as the authoritative application identity without authentication, relying on a private network containing trusted users. Per-user ChatGPT connections may be exposed in this mode once ownership handling is established. Later, both Kochwiki and AI Service will participate in SSO through one shared identity provider. Microsoft Entra is a candidate, not a decision; provider selection and active authentication are deferred. ChatGPT provider authorization remains separate from application identity.

Later subscription work adds persistent per-user credentials, initial authorization for the LAN deployment, the subscription-compatible adapter and model catalog, provider selection, and the shared recovery dialog. The current concept does not yet choose the identity provider, initial login helper, credential store, or retry execution strategy. The delivered event transport uses a separate SSE observer.

### Foundation Decisions to Resolve Next

Application identity and ownership is the next discussion topic, to be developed incrementally. Kochwiki is currently the only other application and offers user selection without authentication. In the initial trusted-LAN deployment, the selected user is accepted as the application identity for conversations, shared API-key use, and per-user ChatGPT connection management. This is an explicit trust assumption, not technical verification of the person making the request. ChatGPT account/workspace identity remains separate.

Kochwiki already assigns stable user IDs. Use a temporary, source-prefixed owner identity such as `kochwiki:42` for the initial trusted-LAN mode. Ownership depends on the stable ID, not the display name. A separate AI Service user-ID mapping is not required for this initial mode.

Kochwiki supplies the selected identity through the `X-Application-User` request header, for example `X-Application-User: kochwiki:42`. Conversation and connection-management requests, including SSE observation, carry this header. AI Service uses the supplied identity to assign and check resource ownership. The header carries application identity only, never ChatGPT credentials, and is trusted without authentication in the initial LAN mode.

The standalone AI Service frontend currently provides only the UI demo. It supplies a fixed demo user identity through the same header instead of introducing a user selector. Use a distinct demo identity, such as `demo:default`, separate from Kochwiki user identities; the exact literal remains an implementation detail. All visitors to this frontend use that same demo owner. This is a frontend-supplied identity, not a backend fallback for unidentified requests, and does not establish the identity flow for any future standalone connection-management screen.

An explicit, valid identity header is required for these requests. Missing, empty, or malformed `X-Application-User` values make a request invalid; AI Service rejects them before accessing conversations or starting work. There is no default user or anonymous fallback. Kochwiki must have a selected user before opening a conversation or managing a ChatGPT connection. Validate only the `source:id` structure: exactly one colon, non-empty source and ID portions, and no whitespace. Do not restrict the source prefix to known applications or verify that the asserted user exists. Invalid headers use HTTP 422 with the typed `request_validation` envelope.

Changing the selected Kochwiki user clears the visible chat and connection status and detaches the UI from the previous user's conversation. The next conversation belongs to the newly selected user. Existing conversations keep their original owner; switching users neither transfers ownership nor cancels an admitted turn. Running work continues under its original owner's identity and provider binding. Updates from the previous user's requests or stream must not repopulate the new user's view. Returning to a previously selected user does not imply conversation resumption; durable history and resumption remain outside the current scope.

The target architecture has both applications participating in SSO through a shared identity and login system. Microsoft Entra is a tentative candidate; the provider and authentication implementation are not the current focus. The contract should separate the application user that owns resources from the mechanism establishing that identity. Preserving existing ChatGPT connections when switching to SSO is not required; users may reconnect under their SSO identities. Mapping temporary owners to SSO identities is not a prerequisite for this concept.

Bind each conversation to its application owner at creation and check the current application identity for session reads, message submission, turn starts, and SSE observation. A resource ID alone does not select its owner. The same ownership principle governs provider registration/import, status, disconnect, model discovery, and credential refresh. In trusted-LAN mode these checks compare against the asserted selected-user identity: they prevent ordinary cross-user mixing but cannot stop someone deliberately selecting or claiming another user. The deployment explicitly trusts users not to do so. The exact request contract remains to be discussed.

Requests for another user's resource return the same not-found response as requests for an unknown resource. Enforce ownership before returning resource data, opening observation, or starting work. This behavior applies to conversations and provider connections; it must not reveal whether another user's resource exists. Invalid identity headers remain invalid requests rather than resource-not-found outcomes.

The ordered-history foundation is implemented. One authoritative ordered, append-only session history retains messages, model continuation items, tool calls, execution outcomes, accepted artifact records, and terminal state. Calls are recorded before execution and history is consumed without re-executing them. Orchestration assigns artifact identity and atomically stores accepted artifacts alongside results and history references. Validated artifacts survive later generation failure; candidates not returned or accepted leave no session artifact state. Safe timeline projections display tool activity and artifacts, including failed-turn survivors, without exposing raw arguments, results, or private reasoning. Per-tool icons and expandable tool details remain deferred.

Backend-owned turns and a separate SSE observer are implemented. Work continues after browser disconnection; a lost stream does not prove execution stopped. The current frontend retains displayed content, reports unknown outcome, and disables submission. Reconciliation, reconnect, refresh recovery, deliberate retry, and user-controlled cancellation remain outside the delivered slice.

Failure reconciliation and deliberate retry are deferred for now, without changing their intended safety requirements. A user message should remain one logical message across retries, with attempts distinguished so failed output and tool outcomes do not merge or disappear. Retry must account for completed and unresolved tool actions. Actual returned results and service-generated reports for missing outcomes remain model context; these reports distinguish execution never started from execution started with an unknown outcome. Retention alone does not guarantee duplicate-mutation prevention. Uncertain mutations may require domain-supported idempotency or status lookup before safe retry.

Retain model history, execution outcomes, and safe UI activity as separate views of the same work. Safe activity summaries are not sufficient model context, and raw tool payloads are not automatically suitable UI events. Keep the existing ephemeral conversation lifetime; durable chat storage is not a prerequisite. Durable provider credentials remain later subscription work.

### First Delivery Slice: Required Identity Header

The first slice is implemented: the required application identity header spans the existing conversation API and frontend transport. It applies to session creation, reads, message submission, turn starts, and SSE observation. Invalid headers are rejected before accessing conversations or starting work, using HTTP 422 and the existing typed validation-error convention. The host supplies an explicit identity to the shared transport; the demo frontend supplies `demo:default`. The generated backend/frontend contract and relevant documentation are updated together. Existing host integrations must supply the header and the transport constructor's required application identity argument.

Verification passed for rejection without conversation access or work, unrestricted prefixes, header delivery on every transport operation including SSE, and the existing demo streaming flow. Backend tests, frontend library and demo tests, generated-contract checks, both frontend builds, and built-package consumer verification passed. This slice establishes identity carriage and format validation only; it does not provide per-user resource isolation. Storing conversation owners and enforcing ownership are the next slice. User-switch behavior, provider connections, and SSO authentication remain subsequent work. Build and tooling configuration are unchanged.

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

Application identity and server-side ownership handling are prerequisites for per-user connections. For the initial trusted-LAN release, accept the selected Kochwiki user as that identity without requiring verified login. Bind each provider registration to this application owner, keeping application identity separate from the validated ChatGPT account/workspace identity. A caller-supplied connection ID does not override ownership. Never select another user's plan as a fallback. Registration/import, status, disconnect, model discovery, conversations, and refresh handling must respect ownership under the accepted identity. Verified SSO authentication will later replace the trusted assertion; it is not a blocker for the initial connection feature.

The configured API key belongs to the deployment and remains backend-only. Every application user identified under the active identity mode is allowed to use its shared API budget in the initial release, without separate administrator approval or a per-user budget entitlement. Users without a connected plan use this baseline automatically. The initial deployment requires a selected application identity and trusts private-network users without verifying login. Later SSO will authenticate that identity. Existing domain permissions remain owned by the domain service. Per-user spending controls are outside the initial scope. Existing bounded turn and tool execution limits remain applicable.

### Remote Deployment Connection Flow

The agreed deployment is a server in the local network, accessed by users from browsers on other computers. Treat it as remote for OAuth callback handling. The documented open-source flow uses a loopback callback on the computer running the browser. A LAN AI Service URL is not a substitute for that callback.

Recommended candidate: complete registration and OAuth through an AI Service local helper, then securely import the selected protected registration into the server. Preserve the server's stable host ID and let the server exclusively own subsequent refreshes. Reconnection repeats an explicit local authorization/import flow. Do not keep refreshing the same transferred credential session independently on both machines.

The helper is only for initial connection and exceptional reconnection; it is not required while using the application. Prefer an application-managed setup command that handles authorization and secure transfer together, rather than asking users to copy raw tokens. Import must bind the registration to the application user established by the active identity mode and verify the provider identity and consent; users should not need server administration or shared SSH access. The helper's secure handoff and user experience remain unresolved recommendations.

Keep credentials in backend-only persistent storage on the LAN server. If the service is containerized, that storage must survive container replacement and image upgrades. Keep the server host identity stable across those operations. The storage mechanism and secure transfer method remain to be selected; no deployment configuration changes are implied by this concept update.

Persist the issued registration, validated account identity, granted scopes, expiry, and rotating credentials separately from ephemeral conversations. Serialize refresh operations for each connection and replace refreshed credentials atomically. Distinguish local disconnect, upstream revocation, and reconnect-required states. The preview does not yet provide host-specific usage attribution or revocation for transferred sessions.

### Adapter and Model Selection

Use the public Responses endpoint with OAuth bearer credentials. Keep subscription-specific request construction behind the model provider boundary; reuse orchestration and domain tools. A separate subscription adapter is the tentative preference over conditionals spread across the runtime.

Discover models using the selected account's catalog, display the provided names, and send the selected slug. Never assume the API-key catalog or fixed Kochwiki model is available to this account. Decide later whether the initial UI offers a model picker or uses an explicitly configured account-available default.

Set `stream=true` and `store=false`, send required history in an input array, and use instructions or developer guidance. Omit unsupported fields, including the current output-token limit. Adapt function tools into the documented namespace or additional-tool format while preserving stable runtime call identities. Domain MCP discovery and execution remain local to AI Service.

Continue enforcing service limits on provider responses, tool attempts, input/history size, time, and accepted output. Removing an unsupported provider parameter must not remove bounded orchestration. Exact limits and event schemas belong in the later specification.

### Streaming and Tool Transparency

The delivered provider-neutral event contract is owned by AI Service. A turn POST admits backend-owned work and returns HTTP 202; a separate GET observes it through SSE. Typed snapshots, ordered item upserts, closing notifications, terminal outcomes, and observation errors keep the backend, generated contract, conversation transport/controller, and shared UI aligned. The `/ui` entry point remains independent of network access.

The delivered stream exposes complete messages, tool preparation, execution and outcomes, accepted artifacts, and terminal turn state with stable identities and ordering. Complete-message delivery is the current text boundary; token-by-token text and argument-fragment delivery are not required by the delivered foundation. Parallel execution is not itself required for this provider integration.

Execute a tool only once complete arguments have been received and validated. Runtime execution determines completion or failure; a provider function-call event alone cannot establish the tool's execution outcome. The current UI exposes tool names and safe statuses. Any future labels or expandable input/result summaries must exclude credentials, sensitive payload fields, and private model reasoning.

Keep streamed text provisional until successful turn completion. Provider success requires its completed event; an interrupted, incomplete, or failed stream is a distinct failure even after text has appeared. A whole agent turn succeeds only after orchestration and artifact acceptance also complete.

### History, Failure, and Recovery

Retain model context separately from display history and safe activity summaries. Preserve required provider output items, complete tool calls, and their results across turns within the existing ephemeral session lifetime. Durable conversation storage is not required; durable credentials are.

Retain an authoritative record of tool execution outcomes when a provider response fails after a tool ran. Replay both completed and unresolved calls, using clearly identified service execution reports for missing results rather than omitting the exchange or fabricating a tool return. Preserve confirmed results alongside uncertain ones. Completed, validated tool-produced artifacts survive later generation failure, while candidates not returned or accepted leave no artifact state. Domain proposals remain independent of presentation artifacts. Never imply a turn failure rolled back domain work, and never automatically repeat a potentially state-changing tool because the UI connection was lost.

Deferred recovery direction: UI transport loss should trigger session/turn reconciliation without silently replaying the turn. The delivered backend keeps work running after disconnect, while the UI reports unknown outcome and disables submission. User-controlled cancellation is not implemented; its stopping behavior and terminal outcomes remain future decisions. Cancellation cannot undo a tool already completed.

### Shared Plan Recovery Dialog

Plan access or usage failures detected during token refresh and inference use the same user-facing recovery mechanism. Preserve the actual reason internally and show a safe explanation in one shared dialog asking whether the user wants to switch to the deployment's shared API key. The detection point does not change the user's decision or the billing-switch behavior.

- A refresh failure that prevents plan use stops the affected operation and surfaces the dialog to the owning user. If detected in background refresh while no UI is connected, retain the recovery state and surface it when that user next interacts; browser presence is not required for background refresh.
- An inference failure, including one received after streaming begins, fails the turn and opens the same dialog. Keep any streamed text visibly incomplete and retain the failed user message for retry.
- Accepting switches the user's selected billing mode to API-key usage. Do not automatically resend the request or append a duplicate user message. The user explicitly retries the failed message within the existing conversation.
- Declining leaves plan mode selected and does not incur API-key charges. Reconnection or a later retry can remain available as appropriate to the reported cause.

Error classification still determines credential lifecycle: retain credentials for temporary failures, clear unusable tokens for confirmed terminal refresh errors, and keep subscription-limit state separate from token expiry. Unsupported requests, configuration defects, domain/tool errors, and unrelated transport failures remain ordinary errors rather than reasons to change billing.

Retry must account for tool executions that completed before the failure, preserving their outcomes and avoiding duplicate state-changing actions. Switching providers does not roll back domain work. The current frontend leaves submission disabled after observation loss and offers no retry action. Repeated backend starts return the existing turn identity, including a confirmed failed terminal turn; there is no explicit operation to start a new attempt for that failed message. Deliberate retry and replayable cross-provider context therefore require changes to the conversation lifecycle. Model selection must also be validated for API-key mode rather than assuming a plan-only model is available there; the concrete retry and model-mapping contract remains specification work.

Preserve the app-owned error envelope before streaming begins; after headers are sent, use a typed terminal error event. Both feed the same recovery state and dialog. Repeated reports of the same issue should update that state rather than open competing dialogs. Exhausted subscription access must never trigger automatic paid API-key fallback.

## Scope Boundaries

- Eligible Responses inference and client-executed tools are in scope. ChatGPT memories and conversation history are not.
- Embeddings, image generation, audio, and other unsupported hosted tools retain separate capability and billing paths. Web Search support needs independent verification for the selected model/account.
- No broad domain, filesystem, shell, or network access is introduced by provider authentication.
- The universal agent reuses this provider/runtime work; weather tooling is not a prerequisite.
- This concept does not authorize code changes, deployment/tooling changes, or a general authentication redesign.

## Open Questions

The immediate discussion concerns application identity and ownership. Ordered history and streaming are implemented; failure reconciliation and deliberate retry are deferred for now. Selected-user identity and ownership handling must be resolved before per-user connections are exposed; active SSO authentication is deferred. The recovery questions below remain future work.

1. If a standalone connection-management screen is introduced beyond the current demo frontend, how should it obtain the application identity in trusted-LAN mode? The demo frontend uses a fixed demo identity; Kochwiki supplies its selected user's temporary `kochwiki:<user-id>` identity. Both use the required `X-Application-User` header. Unidentified or malformed requests are invalid, and resources belonging to another user appear not found. Shared SSO remains the target for both applications, with provider choice deferred and no requirement to preserve existing ChatGPT connections during that transition.
2. For the confirmed LAN server deployment, is an application-managed local setup command acceptable for initial connection and exceptional reconnection? What server/container topology, protected credential store, and secure transfer method fit the deployment?
3. Should connection management initially be an operator workflow, a shared AI Service screen linked from hosts, or an embedded host settings component?
4. Should a model be selected per new conversation or supplied by configuration after account-catalog validation?
5. When deferred recovery work resumes, how should the UI reconcile a lost stream and recover after refresh? Backend work already continues after disconnect. Should user-controlled cancellation be introduced, and what stopping behavior should it guarantee?
6. How will explicit recovery handle unresolved calls and possible duplicate domain actions, and how should later expandable tool details work? Ordered tool activity and retained failed-turn artifacts are displayed through snapshots and streaming. Backend retention and replay boundaries are implemented; deliberate retry remains deferred.
7. Where should the optional plan-connection prompt, shared recovery dialog, and provider/billing indicator appear? How are explicit retry and model selection represented when switching the existing conversation to API-key usage?

## Risks

The initial trusted-LAN mode does not authenticate selected users. Anyone able to reach the application and assert another user's identity could access that user's conversation or connection-management actions and use their connected plan through AI Service. The deployment explicitly accepts this impersonation risk and trusts network users not to exploit it. Ownership checks prevent accidental mixing, not deliberate impersonation. Provider tokens remain backend-only. Verified shared SSO is the target for both applications.

The current process-wide API-key client may serve the baseline, but subscription requests require per-user credential resolution. The deployment owner bears API costs for users using the baseline; the initial release deliberately has no per-user spending controls.

Credential persistence and ephemeral conversation state have different lifetimes. Disconnect, account switching, refresh races, and in-flight requests must not accidentally cross connections.

Streaming is implemented across the UI contract, but a lost observer still leaves the frontend unable to establish the outcome. Deferring reconciliation and retry preserves this limitation. Future subscription recovery must resolve it before offering a safe retry after a billing-mode switch.

## Sources

- [Registration and sign-in](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)
- [Self-hosted VMs](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms)
- [Models and inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)
- [Preview limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)
- [Errors and recovery](https://developers.openai.com/siwc/token-sharing-open-source/errors-and-recovery)

## Summary

Allow every application user identified under the active identity mode to use the shared API-key baseline without separate administrator approval. Offer optional plan connection and prefer each user's connected plan for eligible new conversations. Refresh and inference failures share one recovery dialog: an explicit switch to API-key usage permits manual retry in the existing conversation, without automatic resubmission or duplicated tool actions. Keep credentials persistent and isolated per user on the LAN server with automatic refresh. The ordered-history and end-to-end API-key streaming foundations are delivered. Defer failure reconciliation and deliberate retry for now, and discuss application identity and ownership next. Initially accept the selected Kochwiki user without authentication inside the trusted private network, and allow per-user plan connections under that ownership contract. Both applications will later participate in shared SSO; Microsoft Entra remains only a candidate. Safe retry remains required for the later subscription recovery dialog.
