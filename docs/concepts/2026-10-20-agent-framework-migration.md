# Agent Framework Migration

## Status

Agreed direction as of 2026-10-20: build a Pydantic AI v2 engine alongside the legacy engine, using as much framework functionality and as little custom infrastructure as possible. Reduce maintenance and improve behavioral visibility first; complex workflows remain a future goal. Work proceeds in narrow slices: discuss and approve the scope, implement and review it, then select the next slice. No separate pre-evaluation phase is planned.

The first approved slice is standalone native turn execution with one ordinary tool, multi-turn history, bounded execution and inspectable results. Production wiring remains on the legacy engine while the new engine gains the necessary capabilities. Once ready, perform an explicit cutover and remove obsolete legacy code; there will be no permanent runtime switch. Match what users experience and what the agent can do, not legacy internals. Presentation and timeline expectations are the eventual integration boundary, and may change when justified.

## Context and Goal

AI Service already implements a bounded agent runtime. `agents/tool_turns.py` coordinates repeated model requests and sequential tool execution. `OpenAIAgenticGenerator` adapts Responses streaming, validates completed output and retains continuation items. The conversation store owns admission, history, execution outcomes, artifacts and notifications; the HTTP/SSE layer projects that state for the frontend.

The goal is to replace generic infrastructure where a maintained framework can reduce our total code and testing burden, while preserving clear service ownership and observable conversation behavior. A shorter model invocation example is insufficient evidence: include adapters, lifecycle management, dependencies and regression coverage in the comparison.

Pydantic AI v2 is available as a stable major line according to the official [upgrade guide](https://pydantic.dev/docs/ai/project/changelog/). This is a custom-runtime migration directly to v2, not a Pydantic AI v1 upgrade. Pydantic AI and the already installed Pydantic validation package are separate dependencies. The implementation pins `pydantic-ai-slim[openai,mcp]==2.58.0` and requires OpenAI SDK `>=3.26,<4` on Python 3.13. The MCP extra supplies the framework's FastMCP client integration.

## Focused Comparison

The dispositions below are architectural proposals, not proven deletions. References to framework features describe documented support; preservation of our particular semantics still needs verification.

| Responsibility | Current implementation | Candidate with Pydantic AI v2 | Expected disposition and tradeoff |
| --- | --- | --- | --- |
| Model integration | `openai_agentic_generation.py`, generation request/response models and `AgenticGenerator` | Framework model/provider integration and typed messages | Replace most custom request/stream parsing. Verify Responses settings, encrypted reasoning continuation, `store=False`, timeouts and hosted tools before claiming parity. |
| Model/tool loop | `tool_turns.py` and `ModelTurnStrategy` | Framework agent run | Replace the generic loop; retain a small service-facing turn executor. Running the framework under our existing loop would leave most maintenance in place. |
| Tool registration and invocation | `ToolRegistry`, `RegisteredTool`, `ToolSource` | Function tools, toolsets and capabilities | New engine uses native MCP discovery and schemas directly alongside local tools; no legacy registration adapter. |
| Execution limits | 32 registered-tool attempts, 40 provider responses, separate hosted-search budget | Framework usage limits plus application policy where needed | Partial replacement. Framework counters and failure behavior are not equivalent to current limits. |
| History and continuation | Session-owned records; `generation_history.py` records output and `history_projection.py` produces model input | Native framework messages for model continuation; application projection for display | Redesign the boundary without recreating legacy generation records. Do not retain two independently mutable model histories. Preserve cross-turn context and useful output from failed turns. |
| Timeline and streaming | Completed messages, requested/running/outcome calls and artifacts admitted during execution | Framework events/hooks projected for presentation | Preserve truthful user-visible activity; exact timeline representation is open to justified changes. Event mapping is new maintenance, not a free feature. |
| Artifact publication | Local tools produce candidates; `ConversationSessionStore.record_result()` accepts and publishes them atomically | Framework tool invokes the same service acceptance boundary | Keep identity, ordering, capacity and publication in service code. The next model request must receive the accepted result, including the assigned artifact ID or rejection. |
| MCP transport and availability | `AgentRuntime`, `MCPConnection`, `MCPToolset` own discovery, polling, retry and reconnect | Framework-managed MCP in the new engine | Standalone native integration delivered in the second slice. Preserve tool access and domain instructions without recreating custom polling and recovery policies by default; application availability integration remains later work. |
| Sessions and public API | `ConfiguredAgentService`, session store, owner checks, reservations, expiry, HTTP and SSE | Application boundary around native execution | Retain product responsibilities; their internal implementation may change. Deliver justified public-contract changes with the frontend. |
| Diagnostics | Internal history and application logs; no dedicated agent tracing/evaluation integration identified | OpenTelemetry instrumentation and optional Pydantic Evals | Add execution visibility and repeatable behavioral comparisons. Trace storage/viewing and evaluation cases still need choices and maintenance. |
| Deterministic demo | `demo/turns.py` explicitly scripts calls using shared history helpers, registry and session lifecycle; it does not use the model/tool loop | Existing script path with updated shared helpers, or framework test/function model | Prefer retaining the script unless shared-helper replacement makes a framework model simpler. Do not require live credentials or remote services, or keep a complete legacy production runtime solely for the demo. |

Pydantic AI documents [agent execution and streaming](https://pydantic.dev/docs/ai/core-concepts/agent/), [custom toolsets](https://pydantic.dev/docs/ai/tools-toolsets/toolsets/) and [capability-based hooks](https://pydantic.dev/docs/ai/core-concepts/hooks/). These provide plausible integration surfaces; no runtime experiment has established the proposed savings yet.

## Agreed Direction

Pydantic AI owns model/provider integration, the agent loop, tool dispatch, model continuation messages and MCP integration. Prefer its native limits, completion, validation, retry configuration and events. Remove the custom generator protocol, Responses parser and generic tool loop rather than retaining them behind an adapter or fallback.

AI Service owns application identity, session expiry, turn admission, public timeline projection and artifact acceptance. Native messages supply model continuation; application records supply the public timeline and lifecycle. These are different representations with explicit ownership, not independently editable copies of the model conversation. Keep complete output and accepted artifacts visible after a later failure, and distinguish calls that never started from uncertain outcomes.

Use native MCP integration instead of preserving the custom polling/reconnection runtime by default. Framework-managed discovery and lifecycle may replace those policies. Configure failures and tool execution so mutations are not automatically repeated after an uncertain outcome. Retain server-owned domain instructions and validation.

Adopt framework completion and budgets rather than replicating the exact custom counters or requiring a provider-specific final-answer phase to end every run. Preserve available phase metadata for display. Use framework-supported execution controls where needed to keep artifact and call ordering reliable.

Update shared demo helpers as necessary while keeping the demo deterministic and independent of live credentials. Do not retain a parallel legacy production engine for tests or the demo. Retarget meaningful regression tests to native framework models and tools; remove tests that exclusively verify deleted infrastructure and explain those removals.

Build the new engine independently of legacy execution abstractions. Do not dual-execute real requests, since tools may have side effects. Resolve concrete issues within each approved slice and update this concept with resulting choices. Public API changes are acceptable when justified and must ship with this repository's frontend together.

## Understanding and Improving Behavior

Tracing should correlate an agent run with its service turn and show model requests, tool choices, results, errors, duration and usage where available. It can explain the execution path and reported rationale, not reveal private model reasoning or prove why a choice was made.

Pydantic AI uses OpenTelemetry; Logfire is an optional viewer/backend rather than a required hosted service. Decide the destination and content capture before exporting prompts, tool inputs or results, since these exceed the deliberately limited public timeline. See [observability documentation](https://pydantic.dev/docs/ai/integrations/logfire/).

[Pydantic Evals](https://pydantic.dev/docs/ai/evals/evals/) can assess outputs and tool-call trajectories independently of migration. Candidate Kochwiki cases include retrieving enough context before proposing a change, avoiding premature saves, reporting explicit tool failure accurately, and continuing a later conversation turn without repeating earlier mutations. Use controlled tool fixtures; do not evaluate write behavior against real domain data.

Use focused deterministic regressions and small live smoke tests to check implemented slices. Broader model-quality evaluations can follow concrete behavioral questions; they are not a prerequisite for migration. Framework adoption alone is not evidence of better answers.

## Scope Boundaries and Alternatives

Keep ephemeral process-local sessions and the deterministic demo usable. Persistent conversations, user-controlled cancellation, approval UI, automatic mutation retries and new workflow engines remain outside the initial migration direction. Future graphs or durable execution can coordinate agent runs once a concrete workflow justifies them; persistence and duplicate-mutation prevention remain separate design concerns.

Keeping the custom runtime and adding instrumentation/evaluations remains the baseline alternative. Revisit LangGraph if explicit branching and durable workflow control become immediate needs. Revisit the OpenAI Agents SDK if it demonstrably reduces adaptation for the current Responses features. Pydantic AI remains preferred provisionally because the present goals concern typed agent infrastructure and behavioral visibility.

Public API changes are not a goal, but neither are internal legacy wrappers. If a justified API change emerges, deliver backend and frontend together under the repository's internal-contract policy.

## Delivery and Remaining Decisions

Implementation temporarily coexists with the unchanged legacy executor. The first slice lives in `backend/app/agentic/turns.py` and uses native agents, tools, results and serialized message history. It supplies default request/tool budgets, request/tool timeouts and disables automatic SDK and model-validation retries. Framework completion replaces the legacy final-answer-phase requirement. Expected tool failures can use native `ToolFailed`; unexpected exceptions propagate. Native results and `capture_run_messages()` provide local execution inspection; a hosted tracing destination remains undecided.

The first slice includes deterministic tool/follow-up, failure, cancellation, validation and budget tests, plus an offline OpenAI Responses transport round trip. `backend/scripts/verify_pydantic_turn.py` exercises two real-model turns using a harmless local lookup tool and checks that the follow-up reuses history without repeating the call. It requires local credentials and model configuration. MCP, web search, artifacts, application sessions and frontend timeline projection are not part of this slice.

Subsequent slices add the remaining user-facing capabilities before cutover. Use existing behavior tests to expose issues, with framework-native test/function models for deterministic execution. Verify calls and artifacts during execution, cancellation/failure settlement, session isolation, MCP operations and the independent demo. Remove obsolete legacy infrastructure at cutover. Keep frontend validation scoped to actual frontend changes.

The second approved slice adds native backend-executed MCP access in `backend/app/agentic/mcp.py`. Native `MCPToolset` instances plug into the turn agent alongside ordinary tools, include server-owned instructions, discover schemas, and share the agent context's connection lifetime. Domain tools load eagerly as core functionality. Explicit server tool errors become failed results; zero tool retries prevent protocol errors from starting a model-retry cycle. Transport failures propagate. Optional task execution is not preferred. MCP timeouts live with the other execution defaults in `app/agentic/config.py`. No legacy connection classes, registry, polling or reconnect loop are reused.

Deterministic tests exercise the native client and a real MCP server through in-process Streamable HTTP: instructions, schema discovery, local/MCP coexistence, successful execution, serialized follow-up history, explicit tool failure, connection failure and cleanup. A lost-response case verifies that an operation completed on the server is called once and the transport failure stops the run without replay. That failure can also surface when closing the agent, although the underlying client disconnects. The model can still independently request another call after an explicit failure; these settings are not duplicate-mutation prevention.

`backend/scripts/verify_pydantic_mcp.py` supplies a real-model Kochwiki smoke test with one explicitly selected server-advertised read-only tool, one successful tool result and a native-history follow-up with further execution disabled. The annotation is a server declaration, so the operator chooses a trusted lookup tool. Live verification remains pending because model and MCP configuration are absent locally. Application sessions, frontend timelines, artifacts, web search and production cutover remain outside this slice.

The agreed presentation direction is to observe execution through Pydantic AI's supported APIs and adapt the conversation schemas and frontend handling to native event and message semantics. Preserve user-facing capabilities rather than legacy timeline states; do not introduce an adapter that recreates the old execution representation. Reuse native models where suitable. The application still owns session identity, ordering, artifact publication and selection of public content; native diagnostic payloads are not automatically public. Observation must not become a second orchestration loop. Any public-contract changes must ship with their frontend consumers.

The third approved slice implements backend observation and failure settlement without streaming or frontend adjustments. `app/agentic/observation.py` supplies a single-use `TurnObservation`, passed optionally to `execute_turn()`. Native lifecycle hooks retain the run's history and usage references and record native tool-call parts at the pre-execution boundary. On exit, the capture detaches native messages and usage, retaining run/conversation identifiers even when execution raises or is cancelled. No execution error is suppressed, no legacy status adapter is introduced, and no second model history is maintained during execution. Completed assistant messages and confirmed tool returns remain in captured history; native interrupted markers identify incomplete execution. Started calls distinguish an uncertain dispatched operation from a request that never reached execution.

The framework's event-stream observer enables model streaming, so this slice deliberately uses node and tool lifecycle hooks with non-streamed `agent.run()` instead. There are no token deltas, push event delivery, HTTP/SSE changes, public-schema changes or production wiring. Inspection records contain internal model and tool data and are not yet a public timeline. Native captured history can be serialized and passed into a follow-up; the framework repairs unanswered calls with interrupted results without re-executing them. Such repair does not prevent the model from independently requesting a new mutation.

Regression coverage includes completed text and native results, explicit failure, argument/budget rejection without dispatch, loss of a response after execution, model failure after a confirmed result, cancellation, concurrent turn isolation, capture reuse rejection and serialized interrupted-history continuation. The lost-response scenario preserves one confirmed operation, a second uncertain operation and a third unstarted request. Native MCP transport-loss coverage also captures the interrupted run through connection cleanup. Session integration, live delivery and frontend contract changes remain later slices.

The main remaining choices are native history retention during failed runs, the public subset of native events and messages, artifact admission before model continuation, application availability around native MCP, and an observability destination. These are implementation decisions to resolve as work proceeds, not blockers requiring a new evaluation phase.

The principal risk remains compatibility machinery erasing the maintenance savings. Prefer documented framework APIs and simplify old internal policies when needed. Preserve truthful execution outcomes, access isolation and accepted artifacts. No provider calls or real domain writes are needed for regression testing.
