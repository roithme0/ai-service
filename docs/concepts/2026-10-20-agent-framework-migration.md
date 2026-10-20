# Agent Framework Migration

## Status

Agreed direction as of 2026-10-20: migrate directly to Pydantic AI v2, using as much framework functionality and as little custom infrastructure as possible. Reduce maintenance and improve behavioral visibility first; complex workflows remain a future goal. Implementation is authorized and proceeds directly, resolving issues through working code and regression tests rather than a separate evaluation phase.

The user explicitly authorizes framework-native replacement, the required dependency change and removal of obsolete legacy code. There will be no permanent runtime switch. The comparison below records the starting inventory; framework defaults may replace internal policies where useful. Preserve meaningful product guarantees, not internal compatibility for its own sake.

## Context and Goal

AI Service already implements a bounded agent runtime. `agents/tool_turns.py` coordinates repeated model requests and sequential tool execution. `OpenAIAgenticGenerator` adapts Responses streaming, validates completed output and retains continuation items. The conversation store owns admission, history, execution outcomes, artifacts and notifications; the HTTP/SSE layer projects that state for the frontend.

The goal is to replace generic infrastructure where a maintained framework can reduce our total code and testing burden, while preserving clear service ownership and observable conversation behavior. A shorter model invocation example is insufficient evidence: include adapters, lifecycle management, dependencies and regression coverage in the comparison.

Pydantic AI v2 is available as a stable major line according to the official [upgrade guide](https://pydantic.dev/docs/ai/project/changelog/). This would be a custom-runtime migration directly to v2, not a Pydantic AI v1 upgrade. Pydantic AI and the already installed Pydantic validation package are separate dependencies. An exact framework version and compatibility with Python 3.13, the installed OpenAI SDK and MCP SDK remain to be checked before implementation.

## Focused Comparison

The dispositions below are architectural proposals, not proven deletions. References to framework features describe documented support; preservation of our particular semantics still needs verification.

| Responsibility | Current implementation | Candidate with Pydantic AI v2 | Expected disposition and tradeoff |
| --- | --- | --- | --- |
| Model integration | `openai_agentic_generation.py`, generation request/response models and `AgenticGenerator` | Framework model/provider integration and typed messages | Replace most custom request/stream parsing. Verify Responses settings, encrypted reasoning continuation, `store=False`, timeouts and hosted tools before claiming parity. |
| Model/tool loop | `tool_turns.py` and `ModelTurnStrategy` | Framework agent run | Replace the generic loop; retain a small service-facing turn executor. Running the framework under our existing loop would leave most maintenance in place. |
| Tool registration and invocation | `ToolRegistry`, `RegisteredTool`, `ToolSource` | Function tools, toolsets and capabilities | Replace overlapping abstractions where practical. Dynamic MCP schemas still need an adapter if current connections remain service-owned. |
| Execution limits | 32 registered-tool attempts, 40 provider responses, separate hosted-search budget | Framework usage limits plus application policy where needed | Partial replacement. Framework counters and failure behavior are not equivalent to current limits. |
| History and continuation | Session-owned records; `generation_history.py` records output and `history_projection.py` produces model input | Framework messages mapped into service history, or retained as internal continuation payloads | Redesign the boundary. Do not retain two independently mutable conversation histories. Preserve cross-turn context and partial failed-turn history. |
| Timeline and streaming | Completed messages, requested/running/outcome calls and artifacts admitted during execution | Framework events/hooks translated into service records | Keep service semantics; replace provider-specific ingestion. Event mapping is new maintenance, not a free feature. |
| Artifact publication | Local tools produce candidates; `ConversationSessionStore.record_result()` accepts and publishes them atomically | Framework tool invokes the same service acceptance boundary | Keep identity, ordering, capacity and publication in service code. The next model request must receive the accepted result, including the assigned artifact ID or rejection. |
| MCP transport and availability | `AgentRuntime`, `MCPConnection`, `MCPToolset` own discovery, polling, retry and reconnect | Existing connections behind a framework toolset, or framework-managed MCP | Prefer retaining lifecycle initially. Native integration must be assessed separately against current readiness, snapshots and recovery behavior. |
| Sessions and public API | `ConfiguredAgentService`, session store, owner checks, reservations, expiry, HTTP and SSE | Existing service wraps framework execution | Retain these product responsibilities. There is no identified reason yet to change the frontend contract. |
| Diagnostics | Internal history and application logs; no dedicated agent tracing/evaluation integration identified | OpenTelemetry instrumentation and optional Pydantic Evals | Add execution visibility and repeatable behavioral comparisons. Trace storage/viewing and evaluation cases still need choices and maintenance. |
| Deterministic demo | `demo/turns.py` explicitly scripts calls using shared history helpers, registry and session lifecycle; it does not use the model/tool loop | Existing script path with updated shared helpers, or framework test/function model | Prefer retaining the script unless shared-helper replacement makes a framework model simpler. Do not require live credentials or remote services, or keep a complete legacy production runtime solely for the demo. |

Pydantic AI documents [agent execution and streaming](https://pydantic.dev/docs/ai/core-concepts/agent/), [custom toolsets](https://pydantic.dev/docs/ai/tools-toolsets/toolsets/) and [capability-based hooks](https://pydantic.dev/docs/ai/core-concepts/hooks/). These provide plausible integration surfaces; no runtime experiment has established the proposed savings yet.

## Agreed Direction

Pydantic AI owns model/provider integration, the agent loop, tool dispatch, model continuation messages and MCP integration. Prefer its native limits, completion, validation, retry configuration and events. Remove the custom generator protocol, Responses parser and generic tool loop rather than retaining them behind an adapter or fallback.

AI Service owns application identity, session expiry, turn admission, public timeline projection and artifact acceptance. Native messages supply model continuation; application records supply the public timeline and lifecycle. These are different representations with explicit ownership, not independently editable copies of the model conversation. Keep complete output and accepted artifacts visible after a later failure, and distinguish calls that never started from uncertain outcomes.

Use native MCP integration instead of preserving the custom polling/reconnection runtime by default. Framework-managed discovery and lifecycle may replace those policies. Configure failures and tool execution so mutations are not automatically repeated after an uncertain outcome. Retain server-owned domain instructions and validation.

Adopt framework completion and budgets rather than replicating the exact custom counters or requiring a provider-specific final-answer phase to end every run. Preserve available phase metadata for display. Use framework-supported execution controls where needed to keep artifact and call ordering reliable.

Update shared demo helpers as necessary while keeping the demo deterministic and independent of live credentials. Do not retain a parallel legacy production engine for tests or the demo. Retarget meaningful regression tests to native framework models and tools; remove tests that exclusively verify deleted infrastructure and explain those removals.

Start implementing directly. Resolve concrete issues as they appear, and update this concept with the resulting choices. No separate feasibility project, long pre-evaluation or permanent feature switch is planned. Public API changes are acceptable when justified and must ship with this repository's frontend together.

## Understanding and Improving Behavior

Tracing should correlate an agent run with its service turn and show model requests, tool choices, results, errors, duration and usage where available. It can explain the execution path and reported rationale, not reveal private model reasoning or prove why a choice was made.

Pydantic AI uses OpenTelemetry; Logfire is an optional viewer/backend rather than a required hosted service. Decide the destination and content capture before exporting prompts, tool inputs or results, since these exceed the deliberately limited public timeline. See [observability documentation](https://pydantic.dev/docs/ai/integrations/logfire/).

[Pydantic Evals](https://pydantic.dev/docs/ai/evals/evals/) can assess outputs and tool-call trajectories independently of migration. Candidate Kochwiki cases include retrieving enough context before proposing a change, avoiding premature saves, reporting explicit tool failure accurately, and continuing a later conversation turn without repeating earlier mutations. Use controlled tool fixtures; do not evaluate write behavior against real domain data.

Compare the baseline and candidate using the same model, settings, instructions, tool catalogues and scenarios where practical. Record unavoidable differences. Separate deterministic contract regressions from variable model-quality scores, and measure request count, tool count, latency and usage alongside correctness. Framework adoption alone is not evidence of better answers.

## Scope Boundaries and Alternatives

Keep ephemeral process-local sessions and the deterministic demo usable. Persistent conversations, user-controlled cancellation, approval UI, automatic mutation retries and new workflow engines remain outside the initial migration direction. Future graphs or durable execution can coordinate agent runs once a concrete workflow justifies them; persistence and duplicate-mutation prevention remain separate design concerns.

Keeping the custom runtime and adding instrumentation/evaluations remains the baseline alternative. Revisit LangGraph if explicit branching and durable workflow control become immediate needs. Revisit the OpenAI Agents SDK if it demonstrably reduces adaptation for the current Responses features. Pydantic AI remains preferred provisionally because the present goals concern typed agent infrastructure and behavioral visibility.

Public API changes are not a goal, but neither are internal legacy wrappers. If a justified API change emerges, deliver backend and frontend together under the repository's internal-contract policy.

## Delivery and Remaining Decisions

Implementation replaces the production path directly and removes obsolete code. Use existing behavior tests to expose issues during migration, with framework-native test/function models for deterministic execution. Verify multi-turn continuation, calls and artifacts during execution, cancellation/failure settlement, session isolation, MCP operations and the independent demo. Keep frontend validation scoped to actual frontend changes.

The main remaining choices are native history retention during failed runs, event-to-timeline mapping, artifact admission before model continuation, MCP lifecycle integration, and an observability destination. These are implementation decisions to resolve as work proceeds, not blockers requiring a new evaluation phase.

The principal risk remains compatibility machinery erasing the maintenance savings. Prefer documented framework APIs and simplify old internal policies when needed. Preserve truthful execution outcomes, access isolation and accepted artifacts. No provider calls or real domain writes are needed for regression testing.
