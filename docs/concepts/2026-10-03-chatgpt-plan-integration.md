# ChatGPT Plan Integration

## Status

Blocked as of 2026-10-07: the intended MVP requires browser-only ChatGPT-plan connection from desktop and mobile to the LAN-hosted Kochwiki application. The documented public plan-access flow requires a callback listener on the user's computer. Local helpers and credential-transfer workflows do not meet the requirement; partner integration is not a viable path for this personal, non-commercial deployment. See the blocker below.

Subscription integration is not implemented and remains a desired outcome in [the planning initiative](../../../plan/Initiatives/ChatGPT%20Plan%20Integration.md), now marked blocked. Ordered history, end-to-end streaming, application identity carriage, conversation ownership, and selected-user host handling are delivered; failure reconciliation and deliberate retry remain deferred. Provider connection ownership, persistent per-user credentials, automatic refresh, and normal-path plan-backed chat remain intended MVP work once authorization is unblocked. Kochwiki deployment also needs a compatible chat-library release and dependency adoption.

Keep the multiple-user, trusted-LAN identity mode and API-key baseline for unconnected users. The first plan-backed chat surface remains the existing Kochwiki chat. Mid-chat recovery, billing switching within failed conversations, and deliberate retry remain later work.

## Context

AI Service uses its configured API key as the baseline for eligible Kochwiki and universal-agent inference when the user has not connected a ChatGPT plan. Offer plan connection to reduce reliance on that baseline, and prefer the user's connected plan for eligible requests. Domain services retain authorization, validation, proposal persistence, and explicit saving. The private, non-commercial deployment's eligibility remains the initiative's planning assumption, not a confirmed determination.

This document owns service-level concept decisions. The central initiative remains authoritative for cross-project intent. Official sign-in, self-hosted, models/inference, preview limitations, and error documentation were rechecked on 2026-10-07. Recheck requirements when implementing the affected integration boundary.

The API-key baseline, multiple-user initial scope, and trusted-LAN identity mode are subsequent user decisions refining the initiative. The central initiative now records the MVP direction and the browser-only authorization blocker. The trusted-LAN exception supersedes this concept's previous requirement for verified application login before exposing per-user connections; alignment with DEC-002 remains cross-project follow-up.

## Current Implementation

- `backend/app/agents/wiring.py` creates a process-wide API-key client and fixed-model Kochwiki agent at startup. Missing an API key currently makes that agent unavailable. There is no universal model-backed configuration or provider connection lifecycle.
- `backend/app/models/openai_agentic_generation.py` uses streamed Responses, explicit input history, instructions, and `store=False`. It sends `max_output_tokens` and supplies ordinary function tools. Subscription access still requires different request construction and supported tool packaging.
- The shared session lifecycle retains an ordered, append-only history of messages, provider continuation items, tool calls, execution outcomes, accepted artifact records, and terminal state. `backend/app/sessions/tool_turns.py` records calls before execution and results when returned. Later ordinary model turns replay that history without invoking recorded tools, including service-generated reports for calls that never started or have an unknown outcome.
- The session store retains history and artifacts in process memory for 90 minutes. A completed tool's validated artifact survives later generation failure or cancellation; candidates not returned or accepted leave no session artifact state. Accepted artifacts are available during active turns through safe snapshots and streaming, and retained artifacts consume session capacity. The frontend displays ordered tool activity and artifacts, including failed-turn survivors. Turn failure does not roll back domain work already performed by tools.
- The HTTP API admits backend-owned turns with HTTP 202 and exposes a separate SSE observer. Typed snapshots, item upserts, closing notifications, and terminal events reach the conversation controller and shared UI. Streaming publishes complete messages and tool preparation/execution/outcome updates; token-by-token text and argument fragments are not part of the delivered UI contract. Work continues when a request or observer disconnects. Lost observation leaves the outcome unknown and submission disabled; reconnect, refresh recovery, deliberate retry, and user-controlled cancellation are not implemented.
- The conversation HTTP boundary requires `X-Application-User` and validates its `source:id` structure without restricting prefixes or looking up users. The shared transport sends the host-supplied identity on every request, including SSE; the demo supplies `demo:default`. This identity is trusted without authentication. Each conversation stores an immutable owner with its ephemeral session metadata. Reads, message submission, turn starts, and SSE observation require the same asserted identity, with another owner receiving the existing not-found response before conversation access or work. Provider connections are not implemented.

## Proposed Direction

### Current Blocker: Browser-Only Plan Authorization

The MVP requires browser-only connection from Kochwiki on desktop and mobile, with no callback listener, setup command, or helper installed on the user's device. The deployment is a private, non-commercial LAN server. Local authorization followed by credential transfer does not meet this requirement, and partner integration is not a viable path for this use case.

The documented public ChatGPT-plan OAuth flow requires an HTTP loopback callback on `127.0.0.1` on the computer running the browser. It cannot be replaced with Kochwiki's or AI Service's LAN-server callback. The documented self-hosted procedure still authorizes locally before transferring credentials. This prevents the intended browser-only desktop/mobile connection flow. [Registration and sign-in](https://developers.openai.com/siwc/token-sharing-open-source/sign-in#2-start-authorization), [self-hosted VMs](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms).

The separate website flow supports registered remote callbacks but is documented for selected partners and identity scopes. Website identity login alone does not grant permission to use the user's ChatGPT allowance for inference. No supported browser-only remote-callback plan-authorization path has been established for this deployment. This is a limitation of the currently documented integration route, not a claim that OAuth cannot support the architecture in principle. [Website sign-in](https://developers.openai.com/siwc/website), [client registration](https://developers.openai.com/siwc/request-client-id).

Revisit implementation only when a documented and available route supports both the remote callback and explicit ChatGPT-plan-use authorization for this personal deployment without local software. The intended flow remains Kochwiki browser → OpenAI login/consent → remote callback with an authorization code → AI Service exchanges and validates the code, stores credentials per application user, and refreshes them server-side. Provider tokens should not pass through Kochwiki frontend JavaScript. API-key chat remains available; this blocker neither removes that path nor authorizes automatic paid fallback.

### MVP: Connect a Plan and Use Chat

The agreed immediate goal is successful ChatGPT-plan authorization followed by usable multi-turn model-backed chat. Mid-chat error resolution is secondary. Once the authorization blocker is resolved, deliver the normal connection and inference path first; the fuller recovery design below remains a later target and does not gate this MVP.

#### Required behavior

- An application user explicitly authorizes their own ChatGPT account and plan usage. AI Service retains the issued registration, validated identity, granted scopes, expiry, and credentials under that application owner. A valid identity token without plan-use permission is not a usable plan connection.
- Connections and the server's stable host ID survive backend restarts and container replacement. Refresh works automatically during ordinary use, with refreshes serialized per connection and rotating credentials replaced atomically. Initial authorization and exceptional reconnection may require user interaction.
- A new model-backed conversation resolves and retains its application owner, billing mode, selected connection where applicable, and an account-available model. Connecting or replacing an account does not silently redirect existing conversations. The in-flight binding remains stable.
- Eligible plan requests use the public Responses endpoint with OAuth bearer credentials, streaming, explicit input history, and storage disabled. The subscription adapter omits unsupported fields, including both current token and hosted-tool limits, and packages function tools in a supported namespace or additional-tool format. Local MCP discovery and execution remain AI Service responsibilities; runtime bounds remain enforced.
- Successful subsequent messages retain the conversation context and any local tool results. The existing timeline and artifact behavior are reused. Plan inference does not depend on a configured API key being present; Kochwiki still requires its domain connector.
- Users without a connected plan retain the API-key baseline. A connection blocked by refresh, access, or allowance failure remains a connected-but-unusable plan, not an unconnected user eligible for automatic fallback.
- Basic failures terminate or block the affected operation and show a safe explanation. Interrupted streams are failures rather than successful partial replies. Keep existing recorded outcomes and accepted artifacts. No automatic replay or paid fallback is introduced.

#### Intended path after the blocker is resolved

Connection starts in Kochwiki's browser UI for the selected application user and works on desktop and mobile without local software. OpenAI should return an authorization code to a registered remote callback; AI Service should exchange it, validate identity and plan-use consent, and retain tokens server-side. Kochwiki displays sanitized connection status and returns to its existing chat. This is the desired architecture, not a currently supported public plan-access flow.

The local-helper and operator credential-transfer candidates are excluded from this MVP. Do not implement them as a substitute or assume that ordinary website identity login grants plan access. Storage and model recommendations below are conditional on resolving the authorization blocker.

Prefer a protected backend credential directory on persistent storage for the first single-process deployment, with atomic updates and restrictive access. A database, encryption-key arrangement, persistent mount, and deployment topology remain choices to resolve. This is a recommendation, not authorization to change deployment or tooling configuration. Conversation storage stays ephemeral.

Prefer one configured plan-model default validated against the selected account's catalog before starting chat, rather than a full model-picker UI. If unavailable, expose a configuration/selection error; do not silently substitute the API-key model. The model-selection policy is still tentative.

The first chat surface is the existing Kochwiki chat. Reuse its selected-user identity, conversation controller, streaming timeline, and domain tools. Adopting a compatible released chat library is a rollout dependency. A standalone model-backed AI Service screen is outside this MVP; the existing deterministic demo remains a scripted UI demo.

#### Integration implications

The process-wide fixed generator in agent wiring cannot represent multiple users' connections. Resolve a session-bound provider/model behind the existing generation boundary and obtain current credentials when issuing requests. Keep tools, domain instructions, and domain context independent of billing mode. Separate agent availability from the deployment API key so a valid plan connection can operate without that key.

Provider errors currently collapse into generic adapter exceptions and failed turns. The MVP needs enough typed classification for connection status and a safe failure explanation, including permission, model, allowance, and reconnect-required cases. The comprehensive shared recovery dialog, attempt-aware retry, and cross-provider replay are not required for this first delivery.

#### Evidence that the MVP works

A user completes authorization with plan-use consent and sends multiple chat messages through the existing Kochwiki chat using OAuth rather than the deployment API key. Backend restart retains the connection, and an expired access token is refreshed without another login. Owner checks isolate connection status and inference across two application identities. A local MCP call and its result survive into a subsequent model turn with the existing artifact and explicit-save behavior. Users without a connection can still use the configured API-key baseline. Revoked or exhausted plan access stops clearly and never starts API-key inference automatically.

#### Deferred recovery and product work

Defer the shared billing-switch recovery dialog, retry of a failed message, transport reconciliation, refresh/resumption of conversations, user-controlled cancellation, account/workspace migration of active chats, richer tool details, and broad settings/model-picker UI. Reconnection outside a failed conversation remains part of the credential lifecycle. Until deliberate retry is implemented, a user may reconnect and start a fresh conversation; the UI must not imply that this undoes prior tool work.

### Prerequisites and Starting Point

The ordered-history and streaming foundations are delivered through the existing API-key mode. Failure reconciliation and deliberate retry are deferred for now. Application identity carriage and conversation ownership are implemented; selected-user host integration is locally verified and remaining provider connection ownership work does not depend on completing retry first. Deferral does not remove safe retry as a requirement for the later subscription recovery dialog. This is conceptual dependency ordering, not an implementation specification.

| Foundation | Why it is needed | Evidence that it is ready |
| --- | --- | --- |
| Explicit turn lifecycle and retained execution context | Streaming and retry require an authoritative distinction between running, completed, failed, and uncertain work. Subsequent turns need prior tool calls and results. | Implemented in the backend: multi-turn API-key conversations replay required context, actual returned outcomes, and explicit reports for unresolved calls; completed artifacts survive later failure. |
| Streaming through provider, runtime, HTTP, controller, and UI | Users need text and observable tool activity before completion. Internal provider streaming alone is insufficient. | Implemented: complete messages, tool preparation/execution/outcomes, and accepted artifacts stream through backend-owned turns and a separate SSE observer to the UI. |
| Failure reconciliation and deliberate retry | A disconnected UI must not trigger duplicate execution; a confirmed failed turn must permit an explicit retry without another user-message append. | Deferred for now. Future readiness requires connection-loss reconciliation and explicit retry that preserves the message and accounts for completed or uncertain tool actions. |
| Application identity and ownership | Multiple users need conversations and provider connections assigned to the correct application user. | Conversation identity and ownership are implemented: the required header carries a stable asserted identity and each conversation checks its fixed owner in trusted-LAN mode. Host user-switch integration is implemented and locally verified, with release adoption pending. Provider connection ownership remains subsequent work. Verified SSO login is deferred and does not block exposing connections in this mode. |
| Provider selection at safe turn boundaries | The recovery dialog must be able to change billing mode without changing domain behavior or losing conversation context. | Provider/model resolution is independent of agent configuration; an explicit change applies to the next eligible attempt without resubmitting in-flight work. |

The delivered foundations establish turn associations, terminal states, retained model/execution context, and live safe timeline updates. They remain useful even for users who never connect a plan. Attempt identity and safe explicit retry remain future recovery work.

The next focus is MVP provider connection lifecycle and plan-backed chat; provider connection ownership is delivered within that scope. Initially, AI Service accepts the selected Kochwiki user as the authoritative application identity without authentication, relying on a private network containing trusted users. Per-user ChatGPT connections may be exposed in this mode once ownership handling is established. Later, both Kochwiki and AI Service will participate in SSO through one shared identity provider. Microsoft Entra is a candidate, not a decision; provider selection and active authentication are deferred. ChatGPT provider authorization remains separate from application identity.

The MVP adds persistent per-user credentials, initial authorization for the LAN deployment, the subscription-compatible adapter and model catalog, and provider selection. The shared recovery dialog follows later. The current concept does not yet choose the identity provider, initial login helper, credential store, or retry execution strategy. The delivered event transport uses a separate SSE observer.

### Established Foundation Decisions

Application identity and ownership is being delivered incrementally; identity carriage and conversation ownership are implemented. Kochwiki is currently the only other application and offers user selection without authentication. In the initial trusted-LAN deployment, the selected user is accepted as the application identity for conversations, shared API-key use, and per-user ChatGPT connection management. This is an explicit trust assumption, not technical verification of the person making the request. ChatGPT account/workspace identity remains separate.

Kochwiki already assigns stable user IDs. Use a temporary, source-prefixed owner identity such as `kochwiki:42` for the initial trusted-LAN mode. Ownership depends on the stable ID, not the display name. A separate AI Service user-ID mapping is not required for this initial mode.

Kochwiki supplies the selected identity through the `X-Application-User` request header, for example `X-Application-User: kochwiki:42`. Conversation and connection-management requests, including SSE observation, carry this header. AI Service uses the supplied identity to assign and check resource ownership. The header carries application identity only, never ChatGPT credentials, and is trusted without authentication in the initial LAN mode.

The standalone AI Service frontend currently provides only the UI demo. It supplies a fixed demo user identity through the same header instead of introducing a user selector. Use a distinct demo identity, such as `demo:default`, separate from Kochwiki user identities; the exact literal remains an implementation detail. All visitors to this frontend use that same demo owner. This is a frontend-supplied identity, not a backend fallback for unidentified requests, and does not establish the identity flow for any future standalone connection-management screen.

An explicit, valid identity header is required for these requests. Missing, empty, or malformed `X-Application-User` values make a request invalid; AI Service rejects them before accessing conversations or starting work. There is no default user or anonymous fallback. Kochwiki must have a selected user before opening a conversation or managing a ChatGPT connection. Validate only the `source:id` structure: exactly one colon, non-empty source and ID portions, and no whitespace. Do not restrict the source prefix to known applications or verify that the asserted user exists. Invalid headers use HTTP 422 with the typed `request_validation` envelope.

Changing the selected Kochwiki user clears the visible chat and connection status and detaches the UI from the previous user's conversation. The next conversation belongs to the newly selected user. Existing conversations keep their original owner; switching users neither transfers ownership nor cancels an admitted turn. Running work continues under its original owner's identity and provider binding. Updates from the previous user's requests or stream must not repopulate the new user's view. Returning to a previously selected user does not imply conversation resumption; durable history and resumption remain outside the current scope.

The target architecture has both applications participating in SSO through a shared identity and login system. Microsoft Entra is a tentative candidate; the provider and authentication implementation are not the current focus. The contract should separate the application user that owns resources from the mechanism establishing that identity. Preserving existing ChatGPT connections when switching to SSO is not required; users may reconnect under their SSO identities. Mapping temporary owners to SSO identities is not a prerequisite for this concept.

Bind each conversation to its application owner at creation and check the current application identity for session reads, message submission, turn starts, and SSE observation. A resource ID alone does not select its owner. The same ownership principle governs provider registration/import, status, disconnect, model discovery, and credential refresh. In trusted-LAN mode these checks compare against the asserted selected-user identity: they prevent ordinary cross-user mixing but cannot stop someone deliberately selecting or claiming another user. The deployment explicitly trusts users not to do so. The required identity header and conversation ownership checks are implemented; provider connection endpoints remain future work.

Requests for another user's resource return the same not-found response as requests for an unknown resource. Enforce ownership before returning resource data, opening observation, or starting work. This behavior applies to conversations and provider connections; it must not reveal whether another user's resource exists. Invalid identity headers remain invalid requests rather than resource-not-found outcomes.

The ordered-history foundation is implemented. One authoritative ordered, append-only session history retains messages, model continuation items, tool calls, execution outcomes, accepted artifact records, and terminal state. Calls are recorded before execution and history is consumed without re-executing them. Orchestration assigns artifact identity and atomically stores accepted artifacts alongside results and history references. Validated artifacts survive later generation failure; candidates not returned or accepted leave no session artifact state. Safe timeline projections display tool activity and artifacts, including failed-turn survivors, without exposing raw arguments, results, or private reasoning. Per-tool icons and expandable tool details remain deferred.

Backend-owned turns and a separate SSE observer are implemented. Work continues after browser disconnection; a lost stream does not prove execution stopped. The current frontend retains displayed content, reports unknown outcome, and disables submission. Reconciliation, reconnect, refresh recovery, deliberate retry, and user-controlled cancellation remain outside the delivered slice.

Failure reconciliation and deliberate retry are deferred for now, without changing their intended safety requirements. A user message should remain one logical message across retries, with attempts distinguished so failed output and tool outcomes do not merge or disappear. Retry must account for completed and unresolved tool actions. Actual returned results and service-generated reports for missing outcomes remain model context; these reports distinguish execution never started from execution started with an unknown outcome. Retention alone does not guarantee duplicate-mutation prevention. Uncertain mutations may require domain-supported idempotency or status lookup before safe retry.

Retain model history, execution outcomes, and safe UI activity as separate views of the same work. Safe activity summaries are not sufficient model context, and raw tool payloads are not automatically suitable UI events. Keep the existing ephemeral conversation lifetime; durable chat storage is not a prerequisite. Durable provider credentials remain later subscription work.

### First Delivery Slice: Required Identity Header

The first slice is implemented: the required application identity header spans the existing conversation API and frontend transport. It applies to session creation, reads, message submission, turn starts, and SSE observation. Invalid headers are rejected before accessing conversations or starting work, using HTTP 422 and the existing typed validation-error convention. The host supplies an explicit identity to the shared transport; the demo frontend supplies `demo:default`. The generated backend/frontend contract and relevant documentation are updated together. Existing host integrations must supply the header and the transport constructor's required application identity argument.

Verification passed for rejection without conversation access or work, unrestricted prefixes, header delivery on every transport operation including SSE, and the existing demo streaming flow. Backend tests, frontend library and demo tests, generated-contract checks, both frontend builds, and built-package consumer verification passed. This slice establishes identity carriage and format validation only; it does not provide per-user resource isolation. Storing conversation owners and enforcing ownership are delivered in the second slice below. User-switch behavior, provider connections, and SSO authentication remain subsequent work. Build and tooling configuration are unchanged.

### Second Delivery Slice: Conversation Ownership

The second slice is implemented. Conversation creation records the exact asserted application identity as its immutable owner alongside process-local session metadata, with the existing session lifetime. Reads, message submission, turn starts, and SSE observation check that owner before conversation data, work, or observer registration is accessed. Requests under another identity return the existing HTTP 404 `unknown` envelope, identical to an unknown session; ownership is checked before opening the stream. Owners are not included in public snapshots and cannot be changed by later requests.

Admitted turns continue against their original conversation when the caller disconnects or changes identity. Changing identity does not transfer ownership or cancel work. The demo continues to supply `demo:default`, so all demo visitors still share one owner. User-switch UI behavior, provider connections and their ownership, and SSO remain subsequent slices. Identity remains a trusted assertion without authentication.

Verification passed for owner access, cross-user rejection across both agent configurations and all existing resource operations, exact identity comparison, rejection without conversation access or work, session expiry, and admitted work completing for its original owner after the caller changes identity. All 295 backend tests pass. The generated backend/frontend API contract remains unchanged and its freshness check passes.

### Third Delivery Slice: Selected-User Host Integration

The agreed third slice requires Kochwiki to supply `kochwiki:<stable-user-id>` on every conversation request, require a selected user before creation, and clear visible chat immediately when selection changes. The host disposes and discards the previous controller, detaches its observer, and rejects late request/stream updates. The next conversation uses a fresh identity-bound transport and controller, including when returning to an earlier user. Admitted backend work continues for its original owner; there is no ownership transfer, cancellation, or resumption.

AI Service's existing immutable transport identity and controller disposal provide the required lifecycle without a new switching abstraction. A narrow controller guard additionally prevents a host publication or acknowledgement callback that disposes the controller from admitting an old-user turn. Regression coverage includes pending session creation, message append, turn admission, stale stream events, reconciliation, and callback-triggered disposal. All 100 library tests, the library build, and built-package exports/runtime/strict consumer declaration verification pass.

Kochwiki host source implementation is delivered and locally verified. The host requires a selected user, sends its stable identity through the shared transport, and clears visible chat and artifacts, invalidates save feedback, and disposes the previous controller when selection changes. An outstanding save remains pending until it finishes; its old-user feedback is ignored. Tests cover pending creation success/failure, append acknowledgements, stream updates, and fresh conversations after returning to an earlier user. All 484 Kochwiki frontend tests across 41 files pass, including 44 conversation tests, and its local application build passes. The AI Service demo's four tests also pass.

The declared Kochwiki registry dependency is `0.3.0-alpha`, which lacks the required transport identity argument. The direct-link attempt encountered duplicate Angular runtime instances (`NG0203`); successful local verification instead temporarily installed a tarball packed from the rebuilt library with `--no-save --package-lock=false`, preserving manifests and lockfiles. Deployment requires a compatible library release and Kochwiki's locked dependency update; neither registry publication nor build/tooling configuration changes are authorized by this slice. Provider connection management, SSO, resumption, backend cancellation, and retry remain outside this delivery.

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

The required deployment is a LAN server accessed from desktop and mobile browsers. Connection must work without local listeners, helpers, setup commands, or manual credential transfer. The intended remote-callback authorization flow is blocked by the current public plan-access documentation; see Current Blocker above. The documented local-to-VM transfer procedure does not satisfy the chosen experience and is not an implementation candidate.

Once a supported route exists, AI Service owns code exchange, validated account identity and plan consent, persistent per-user credentials, and automatic refresh. Persist the server's stable host ID and credential state across backend restarts and container replacement. Serialize refreshes per connection and replace rotating credentials atomically. Keep this durable state separate from ephemeral conversations. Storage and deployment choices remain later implementation decisions; no deployment changes are authorized here.

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

### Later Delivery: Shared Plan Recovery Dialog

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

The blocking question is external capability: when will a documented, available ChatGPT-plan authorization route support a remote server callback for this personal deployment, usable from desktop and mobile without local software? Website identity login alone is insufficient; partner integration is not a viable route for this use case.

Once that condition is met, resolve the placement of Kochwiki's connect/status controls, protected persistent backend credential storage, and whether a validated configured plan-model default is sufficient initially. The existing Kochwiki chat and browser-only connection requirement are decided. Compatible chat-library adoption remains a rollout dependency.

Mid-chat recovery, attempt-aware retry, completed and uncertain domain actions, explicit billing changes, observation reconciliation, and cancellation remain later work.

## Risks

The initiative is blocked on a supported browser-only remote-callback plan-authorization route. Building an adapter or adding HTTPS to the server does not remove the public flow's loopback requirement. A local helper would exclude the intended mobile/browser-only experience; website identity consent must not be mistaken for plan-use consent.

The initial trusted-LAN mode does not authenticate selected users. Anyone able to reach the application and assert another user's identity could access that user's conversation or connection-management actions and use their connected plan through AI Service. The deployment explicitly accepts this impersonation risk and trusts network users not to exploit it. Ownership checks prevent accidental mixing, not deliberate impersonation. Provider tokens remain backend-only. Verified shared SSO is the target for both applications.

The current process-wide API-key client may serve the baseline, but subscription requests require per-user credential resolution. The deployment owner bears API costs for users using the baseline; the initial release deliberately has no per-user spending controls.

Credential persistence and ephemeral conversation state have different lifetimes. Disconnect, account switching, refresh races, and in-flight requests must not accidentally cross connections.

Streaming is implemented across the UI contract, but a lost observer still leaves the frontend unable to establish the outcome. Deferring reconciliation and retry preserves this limitation. Future subscription recovery must resolve it before offering a safe retry after a billing-mode switch.

## Sources

- [Website identity sign-in](https://developers.openai.com/siwc/website)
- [Client registration](https://developers.openai.com/siwc/request-client-id)
- [Registration and sign-in](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)
- [Self-hosted VMs](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms)
- [Models and inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)
- [Preview limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)
- [Errors and recovery](https://developers.openai.com/siwc/token-sharing-open-source/errors-and-recovery)

## Summary

The intended MVP is browser-only ChatGPT-plan connection from desktop and mobile followed by multi-turn chat in the existing Kochwiki UI. It is blocked: the currently documented public plan-access flow requires a callback listener on the user's computer, and the self-hosted transfer procedure does not meet the chosen experience. Local helpers and partner integration are not viable paths for this MVP. Website identity login alone does not grant subscription inference.

Revisit only when a documented, available route supports remote callbacks and explicit plan-use permission for this personal deployment without local software. Persistent per-user credentials, automatic refresh, provider ownership, account-model validation, and subscription-compatible Responses inference remain intended work. API-key chat remains available. Mid-chat recovery and retry remain deferred; foundation work need not be repeated.
