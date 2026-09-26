# Chat UI Demo

## Status

Implemented. The shared conversation foundation, configured Kochwiki and demo agents, generic HTTP API, and deterministic frontend demo are implemented. Shared frontend modules remain application internals; publication evaluation is deferred.

## Context

The previous AI Service application hosted `@roithme0/chat-ui` through a recipe-specific controller and a hardcoded recipe snapshot. Creating a proposal then depends on Kochwiki's authoritative foodstuff catalogue and resolver. A locally plausible snapshot can therefore produce a rejected proposal when its foodstuff identifiers do not exist in Kochwiki. This makes the application unreliable as a way to inspect the chat UI itself.

The chat UI library accepts host-supplied text messages and JSON-compatible artifacts, and has a fallback JSON artifact renderer. The application supplies session and transport behavior through the domain-independent conversation foundation.

## Decision

Create one shared session and turn foundation, base Kochwiki's agent on it as a restricted configuration of the universal agent, and provide a hello-world-style UI demo using the same foundation. These three outcomes define the scope of this concept. Recovery optimizations and detailed policies for staged proposals are deferred.

Use the AI Service application as a **chat UI demo**. Its responses follow a deterministic sequence of conversation states and content. The demo records and displays each submitted user message, but the message text does not determine the next response. A new session begins the sequence again.

The demo has no LLM turns, now or later. It does not verify model decisions, tool selection, or the behavior of the planned universal agent. A universal agent is a separate consumer of the generic conversation foundation.

The session contract supporting the demo should be generic: messages, ordered artifacts, turn results, and session state should not encode recipes, foodstuffs, or the demo's scripted steps. Demo-specific choreography belongs in a replaceable demo behavior layer, not in the session model or the chat UI library. This keeps the conversation foundation usable by other capabilities, including the planned universal agent, without turning the demo into that agent.

## Shared Agent and Session Foundation

The universal agent can be equipped with any available tools; it does not necessarily expose all tools in every session. Kochwiki's agent is a restricted configuration of that shared agent, with recipe-specific context, instructions, and tools.

Session and turn lifecycle belong to the shared conversation foundation, including turn reservation, concurrency, terminal state, and expiry. The demo uses this same foundation with deterministic turn execution. It must not introduce a parallel lifecycle used only by the demo.

Domain capabilities retain responsibility for their inputs, validation, and domain operations. They do not supply capability-specific session or turn lifecycle hooks. Kochwiki follows the shared lifecycle rather than maintaining its own interpretation of turn completion and failure.

A consistent typed conversation-store interface is a completion requirement of this concept. All configurations use the same conversation operations and result structures, parameterized by their context and artifact payload types. Domain operations may extend or work alongside this interface, but must not replace common lifecycle methods with domain-specific signatures or result structures. Recipe-specific HTTP representations are produced at the HTTP boundary.

Different sessions must be able to execute turns concurrently. The shared foundation prevents overlapping turns within one session through its turn reservation. Short locks may protect store state, but no store-wide or agent-wide lock is held throughout asynchronous turn execution.

### Staged Artifacts

Tools can produce artifacts staged against the active turn. A recipe tool validates and resolves a proposal before staging it; the shared foundation handles its lifecycle without interpreting its recipe payload. Staged artifacts remain available to subsequent tool calls within that turn when needed.

Artifact staging and cleanup belong to the shared foundation and require no recipe-specific cleanup hook. The existing pending-proposal handling motivates this ownership boundary; exact publication, discard, and recovery semantics are not the focus of this concept and remain deferred.

Artifact cleanup does not undo external tool effects. Retaining the execution history, including completed tool calls and their results after a failed assistant turn, is an intended future direction so the agent can retain knowledge of work already performed. That failure and recovery design is outside this concept's current scope; discarding staged artifacts must not be interpreted as rolling back external operations.

### Configuration and Execution

Configuration supplies available tools, instructions, and initial context. A separate execution strategy determines the next action: model-driven execution for Kochwiki, deterministic scripted execution for the demo. Both strategies invoke configured tools through the shared foundation and use its session, turn, and artifact handling.

The demo script determines tool calls and responses independently of submitted message text. It does not emulate an LLM provider. The configuration describes the available capabilities and context, while the execution strategy owns action selection.

Hosts select a named, server-defined configuration, such as `kochwiki` or `demo`, through the shared session entry point. They do not supply individual tools or assemble arbitrary capability sets. The server resolves the selected option to its tools, instructions, context requirements, and execution strategy. A host supplies the required contextual input, such as a recipe snapshot, which is validated for that configuration. Execution strategy remains a separate responsibility internally even though the named option determines which strategy is used.

Application wiring creates one configured agent service instance per server-defined configuration within each process. The recipe improvement and UI demo services are configured instances of the shared service implementation. Each binds its typed store, execution strategy, permitted tools, input validation, and settings such as artifact limits and model selection where applicable. Each service handles multiple sessions; creating a session does not create another agent service. Adding an ordinary configuration must not require adding configuration-specific branches to the shared service.

Each configuration uses a typed instance of the shared conversation store, retaining one lifecycle implementation without forcing unrelated context and artifact payloads into a heterogeneous store. Configuration-specific input validation runs before a session is allocated. The store owns conversation state and lifecycle; the bound execution strategy runs turns. Session and turn execution state, including tool bindings for the active turn, remains local to that session or invocation rather than mutable state on the shared agent service.

Domain entry points receive their configured agent service through server wiring. The generic HTTP entry point uses a registry at the transport boundary and explicitly identifies the configuration in every request. A session addressed through another available configuration is unknown. Execution dependencies belong to the configured service or its bound strategy; callers do not supply model generators or domain resolvers with every turn. Initializing and using the demo remains independent of OpenAI credentials and Kochwiki availability.

The selected configuration stays fixed for the session's lifetime. Conversation and tool results can evolve its context, but switching configurations requires a new session.

## Demo Experience

The demo uses a minimal hello-world configuration with a real, simple tool that produces a staged artifact. Deterministic execution explicitly invokes that tool without consulting an LLM. The tool has no Kochwiki or external-data dependency and uses the shared tool execution and artifact-staging path. Scripted response selection belongs to the demo behavior, while tool execution and session handling belong to the shared foundation.

The minimal tool is `create_greeting(name)`. The script supplies `"World"`; the tool returns a tool result and stages a `demo.greeting` artifact with payload `{"message": "Hello, World!"}`. The UI displays it through the existing JSON fallback. No custom artifact renderer is included in the current scope.

The initial sequence is deliberately small:

1. First submission: show a brief loading state, then an assistant greeting.
2. Second submission: execute `create_greeting("World")`, then display its artifact and an assistant reply.
3. Further submissions: explain that the demo is complete and instruct the user to refresh the page. Refresh creates a new empty session and begins the sequence again. No dedicated restart control is provided; generic error recovery actions remain available.

Every submitted user message is recorded, but its text does not select the response. The sequence and its timing belong to the replaceable demo execution strategy so they can be adjusted without changing the shared session model or chat UI library.

The demo must clearly identify its replies as scripted. Simulated failures, recovery demonstrations, and larger or nested JSON examples are deferred; the initial sequence covers messages, loading, real tool execution, artifact presentation through the JSON fallback, and restart.

## Scope Boundaries

- Keep the demo in the existing frontend `app` project for now. Extracting it into a dedicated UI demo project is a possible later cleanup, not part of this direction yet.
- Keep the reusable `@roithme0/chat-ui` library independent of the demo and of Kochwiki. It receives content and status from its host and emits user submissions and actions.
- Base the existing Kochwiki agent on the shared foundation as a restricted configuration. New recipe features are outside scope. The demo must not require a Kochwiki recipe, foodstuff, resolver, or session.
- Work is confined to this repository. Migrating the recipe capability here is in scope; implementing or completing its integration in the Kochwiki application is not.
- Generalize the current operational baseline: ephemeral process-local sessions, completed responses without streaming, and existing failure and cleanup behavior. Preserve behavior during extraction; obvious, narrowly scoped fixes are allowed, but broader enhancements, durable storage, streaming, user-controlled cancellation, and recovery improvements are outside scope.
- Do not add an LLM mode to the demo. Model-backed agent behavior requires its own verification path.
- Defer recovery optimizations, execution-history retention, and detailed staged-proposal failure semantics. Establish shared ownership without redesigning those policies here.

Implementation proceeds in bounded slices, resolving slice-specific contract and design questions before each slice. The demo must run its complete sequence without OpenAI credentials, model configuration, or a reachable Kochwiki service.

The first slice extracts shared session, turn, and staged-artifact ownership and routes the existing recipe flow through it while retaining the current recipe HTTP contract and UI behavior. Named configurations, generic endpoints, shared tool dispatch, and the demo follow in later slices. A recipe proposal uses the shared artifact identity, with no second proposal identity or duplicate authoritative storage. Maximum artifact count is a shared session setting; the recipe flow supplies its existing limit of 20, counting both retained and currently staged artifacts. Recipe validation and lineage rules remain domain responsibilities.

## Integration Impact

The application uses the generic conversation HTTP contract with fixed `demo` configuration and empty input. The shared controller and transport supply messages, artifacts, and status to the existing chat UI inputs; the generic mapper preserves artifacts for JSON fallback rendering. Recipe frontend types, mapper, fixture, and dedicated tests have been removed. The backend Kochwiki agent remains available.

Kochwiki must also use the shared session and turn lifecycle. Its configuration supplies recipe context, instructions, and available tools; recipe validation and domain operations remain within its capability implementation. The shared foundation must support both this model-driven configuration and the deterministic hello-world demo without a separate lifecycle for either.

The existing recipe-improvement concept remains the source for the recipe capability. Its earlier use of the AI Service application to inspect real recipe proposals does not define the purpose of this new demo.

## Resolved HTTP Decisions

The common endpoint base is `/api/v1/agents/{configuration}/sessions`. Clients create sessions with an optional `input` in an object envelope, read session history, append user messages, and execute turns as separate operations. Published artifacts appear in completed turn responses and session history with shared identity, type, ordering, turn association, and a JSON payload. There is no individual artifact lookup endpoint or session-to-agent lookup map. The current stores remain process-local and expire sessions after 90 minutes. See the [generic conversation HTTP spec](../specs/2026-09-25-generic-conversation-http.md) for the full contract.

## Risks

- A generic session API designed around one scripted sequence could conceal demo-specific assumptions. The demo behavior and contract need separate ownership.
- A scripted demo can look like a working agent to viewers unless its purpose is explicit in the application.
- Removing the current recipe-backed application flow may reduce convenient end-to-end inspection of proposal integration; that integration needs its own verification path.

## Summary

Create a shared conversation foundation used by Kochwiki as a restricted universal-agent configuration and by a deterministic hello-world demo. The demo records real user submissions, advances through a scripted sequence, and executes a real simple tool that stages an artifact without Kochwiki or LLM dependencies. Detailed recovery and staged-proposal policies remain deferred.
