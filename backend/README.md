# AI Service Backend

Minimal FastAPI backend for the AI Service.

## Local development

Use Python 3.13, matching CI and the Docker images. The repository's
`.python-version` selects 3.13 for tools such as uv and pyenv.
Create and activate a virtual environment, then install the project:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
```

Session context is caller-provided JSON. The AI Service validates its structure
and size without knowing recipes, foodstuffs or their relationships.

To enable the Kochwiki agent, copy `.env.example` to `.env` and set
`OPENAI_API_KEY`, `KOCHWIKI_OPENAI_MODEL`, and `KOCHWIKI_MCP_URL`.
The backend loads this ignored file automatically. The MCP URL identifies
Kochwiki's Streamable HTTP endpoint. `KOCHWIKI_BASE_URL` is no longer used.
In deployed environments, supply these values through the process environment or
secret store; never put a real key in tracked configuration. Missing or invalid
local Kochwiki configuration makes every Kochwiki session endpoint return
`503 agent_unavailable`. The deterministic demo HTTP configuration remains available
without model credentials or Kochwiki access. The frontend now uses this demo:
any text advances its introduction, two greeting artifacts in one turn, one scripted failure, and completion sequence.
The artifact turn includes intermediate updates before each tool call to demonstrate
their placement among tool activity, artifacts, and the standalone final answer.
It then invokes the greeting tool with an empty name to display an explicit failed
call without creating an artifact; the turn completes with an explanation.
The following scripted generation failure retains an intermediate update without
a final answer, demonstrating that the update survives the failure and later turns.
The frontend simulates a 405 compatibility error on the next message after completion; the backend still accepts further submissions. Refresh the page to restart with a new session.
The generator receives the conversation and the retained caller-provided context. Kochwiki supplies all domain tools and workflow instructions through
MCP; the AI Service supplies only generic conversational guidance.

Guidance has separate owners: MCP server instructions describe domain workflows;
tool descriptions and schemas describe individual operation contracts; frontend
artifact capabilities describe presentation payloads, headers and metadata.
The AI Service owns generic conversation, execution and presentation guidance.
Keep multi-step domain policies in the MCP instructions rather than repeating
them in tool descriptions or artifact capabilities.

## Pydantic AI engine and session API

The executor in `app/agentic/turns.py` uses Pydantic AI 2.58.0 directly for OpenAI
Responses, tool execution, MCP and conversation history. It powers the
deterministic demo through the session HTTP API and the frontend's `SessionController`.
Kochwiki still uses the custom engine; its backend cutover and legacy removal
remain separate slices.

The native demo subapplication is mounted at `/api/native`, with sessions at
`/api/native/api/v1/agents/demo/sessions` and its own OpenAPI document at
`/api/native/openapi.json`. It owns one shared `FunctionModel` agent and runner
for the application lifespan. Shutdown closes the runner before the agent.
Session initialization advertises the built-in `json` capability with a required
`value` field. Greeting labels are artifact titles, not separate capability types. The script uses `present_artifact` for two valid greeting artifacts
and one deliberate validation failure, then demonstrates a failed turn with
retained commentary and a subsequent successful turn. Script selection reads
the native history; it has no cross-session mutable step counter. No model
credentials, network model requests or Kochwiki access are needed.

`app.agentic.wiring.create_kochwiki_agent()` composes the new engine from existing
`Settings`: `OPENAI_API_KEY`, `KOCHWIKI_OPENAI_MODEL`,
`KOCHWIKI_OPENAI_REASONING_EFFORT` and `KOCHWIKI_MCP_URL`. It returns a native
agent with application conversation guidance, MCP tools/server instructions and
web search enabled. Missing credentials/model or an invalid HTTP(S) MCP endpoint
raise `ValueError` before resource construction; error messages name settings
without including their values. The optional reasoning effort uses its existing
settings validation.

```python
from app.agentic.conversations import AgentConversation
from app.agentic.wiring import create_kochwiki_agent
from app.core.config import get_settings

agent = create_kochwiki_agent(get_settings())
conversation = AgentConversation()
async with agent:
    first = await conversation.execute_turn(agent, "Find a soup recipe.")
    second = await conversation.execute_turn(agent, "Explain that recipe.")
```

Keep one agent context open across conversations. Native context entry connects
MCP and manages the model/provider lifetime; exit closes owned resources.
MCP startup errors propagate instead of producing an unavailable placeholder,
polling, or retrying in application code. There is no production startup/routing
change or automatic fallback. Production session wiring and application availability
policy remain integration work. Pass `artifact_capabilities` to `AgentConversation` for
conversation-owned artifact acceptance and retention. Each turn receives its own
native publication toolset; presentation configuration is not shared agent state.
Configured composition coverage runs with
`python -m pytest tests/test_pydantic_wiring.py`; it uses no live credentials.

The caller keeps the native agent open with `async with agent:`. Use
`app.agentic.conversations.AgentConversation` to retain native history across turns:

```python
conversation = AgentConversation(initial_context={"recipe": {"id": "recipe-42"}})
async with agent:
    first = await conversation.execute_turn(agent, "Find the value.")
    second = await conversation.execute_turn(agent, "Explain that result.")
```

`execute_turn()` returns the native `AgentRunResult[str]` and accepts per-turn
`usage_limits` and additional `toolsets`.
`conversation.messages` returns a detached tuple of native messages;
`conversation.last_turn` returns detached `TurnObservation` inspection data.
Optional `initial_context` must be a JSON object. Creation validates and serializes
it once, preserving nested JSON types and rejecting non-finite numbers and cycles.
The serialized context, including its data-only prefix, is limited to 64,000
characters by `app/agentic/config.py`. Later caller mutations cannot change it.
It seeds a native user-data message, rather than system or agent instructions,
and follow-up turns reuse it through history without appending another copy.
Omission adds no context message; an explicit empty object is retained. Before
the first turn, `messages` exposes a detached context snapshot and `last_turn`
is `None`. Context is internal model input, not a public timeline item. The label
and agent guidance establish a data boundary; they do not guarantee resistance
to instructions embedded in caller data.

Optional `artifact_capabilities` are also snapshotted at conversation creation.
`execute_turn()` automatically attaches the native `present_artifact` tool when
capabilities are advertised. Acceptance atomically checks the conversation's
`max_artifacts` capacity (default 100, configurable down to zero), assigns a UUID
and UTC timestamp, and retains a detached payload before returning the accepted ID
to the model. Duplicate capability types and invalid limits fail at creation.
`conversation.artifacts` returns detached `ConversationArtifact` snapshots in
zero-based publication order, including artifacts accepted during active execution.
They reuse the shared published-artifact envelope and retain the native tool-call
ID. Their `turn_id` is the native run ID, which associates them with their
execution in the session presentation. There is no separate application turn ID.
Publication order is not a position in the public timeline. Accepted artifacts
survive later failure or cancellation and continue consuming capacity. Rejection
publishes nothing and becomes a native failed tool result. Repeated reads and
history continuation do not publish artifacts again; the model can still request
a new publication. No duplicate-publication prevention is added.

```python
conversation = AgentConversation(
    initial_context={"recipe": {"id": "recipe-42"}},
    artifact_capabilities=capabilities,
)
async with agent:
    await conversation.execute_turn(agent, "Present the recipe.")
artifacts = conversation.artifacts
```

Do not also attach another `present_artifact` toolset to that conversation.
The latest settled observation owns the authoritative history. Failed or cancelled
execution retains its completed messages, confirmed results and uncertain started
calls before propagating the original exception. Setup failure before the first
execution node preserves the previous history. An overlapping turn raises
`ConversationBusyError` immediately, without admitting its prompt or queueing it;
independent conversations can run concurrently on one open agent.

One internal turn collection owns lifecycle records and their observations. Active
execution and the latest settled observation are derived from those entries.
Once a newer captured history settles, the superseded observation is released;
earlier lifecycle records remain without retaining repeated cumulative histories.

While a turn is running, history reads show the previous settled turn. Returned results
and snapshots do not share mutable data with the retained conversation. This is
an internal process-local building block, without session authorization, expiry,
durable storage or public timeline projection. The production session store is
not connected. Focused coverage runs with
`python -m pytest tests/test_pydantic_conversations.py tests/test_pydantic_conversation_artifacts.py`.

`app.agentic.runner.AgentTurnRunner` is the consumer-facing boundary for one
configured agent and all its conversations. It creates and owns an internal
`AgentSessionRegistry`; consumers do not construct or access that registry:

```python
from app.agentic.runner import AgentTurnRunner

runner = AgentTurnRunner(agent)
created = runner.create_session(
    owner="recipe-app:user-42", initial_context={"recipe": {"id": "recipe-42"}},
)
async with agent, runner:
    await runner.submit(created.session_id, owner="recipe-app:user-42", prompt="Explain the recipe.")
    snapshot = runner.read_session(created.session_id, owner="recipe-app:user-42")
    # Keep the application running here; leaving the context shuts down active work.
```

The registry owns session IDs and a fixed 90-minute lifetime, configured in
`app/agentic/config.py`. The runner accepts an optional `session_lifetime` and clock
for configuration and deterministic tests. `create_session()` also accepts artifact
capabilities and capacity. Each runner owns an independent registry.
Every read and turn admission checks the exact owner and expiry; unknown,
other-owner and expired sessions raise the same `SessionNotFoundError`. Owner
identity must come from the application boundary; this check is not authentication.
Reads return detached turn entries and artifacts, never the retained conversation.
Session IDs are distinct from native run/conversation IDs. `snapshot.last_turn` and
`snapshot.messages` derive their data from the latest settled observation in
`snapshot.turns`; they are not separately stored copies. Before captured history
exists, messages come from the detached `snapshot.initial_context_message` seed.

Expiry is inclusive (`now >= expires_at`), and activity does not extend it. An
admitted turn may finish and publish artifacts after expiry, returning its native
result or propagating failure/cancellation normally. Further reads and turns remain
unavailable. Expired registry entries are removed on subsequent registry operations;
an active turn retains its conversation only until settlement. There is no background
cleanup task or cancellation on expiry. Use the registry from one event loop.
Tests inject a timezone-aware clock and lifetime to cover boundaries without sleeps.
History and artifacts remain owned by `AgentConversation`; the registry adds no
execution log, timeline projection or second history store. The runner exposes
presented snapshots through the session HTTP and SSE boundary used by the frontend. Run focused coverage with
`python -m pytest tests/test_pydantic_sessions.py`.

`conversation.turns` and `snapshot.turns` expose admission-ordered `ConversationTurn`
entries. Each entry contains an immutable `lifecycle` (`TurnLifecycle`: `run_id`,
`status`, `started_at`, `finished_at`) and an optional detached native `observation`.
For example, inspect `snapshot.turns[-1].lifecycle.status`. Superseded captures are
released from newer snapshots once a later captured history settles; earlier
snapshots retain their detached observations. Setup failures have no retained
capture. Active captures are detached inspection data and do not supply settled
messages; history reads continue to use the previous settled capture.
An admitted request immediately appears as `running`, then settles as `completed`,
`failed` or `cancelled`, with UTC timestamps. There is no separate application turn
ID. Active reads obtain the native run ID from the existing observation hook;
before that hook runs, the ID is `None`. Setup failures and cancellations can
therefore settle without an ID, while preserving prior native history. Rejected
overlapping or unauthorized requests create no record. Execution does not mutate
existing snapshots; callers may edit their detached observations without affecting
the conversation. Derived message and last-turn views share that snapshot-owned data.

Lifecycle records contain no duplicate messages, tool results or usage. They remain
conversation-owned for the session lifetime and do not change exception propagation
or artifact correlation: artifacts still use the native run ID. A failed or
cancelled execution retains accepted artifacts and captured history; cancellation
does not establish whether an interrupted tool's external effects occurred. Direct
`execute_turn()` calls remain awaited. Focused coverage:
`python -m pytest tests/test_pydantic_turn_lifecycle.py`.

`await runner.submit(...)` waits for admission, then returns without waiting for
completion. Ownership, expiry and the conversation's existing busy guard are checked
inside the background execution; admission failures reach the submitting caller.
The conversation acknowledges admission through the optional internal `on_admitted`
callback before execution can suspend. The runner creates, retains and observes all
background tasks; neither the registry nor the conversation schedules work.
Internally, `sessions.execute_turn()` awaits conversation settlement and returns
the native result or propagates the execution error to the runner. Consumers use
`create_session()`, `read_session()`, `observe_session()` and `submit()`; they do not execute through the
registry. The registry retains internal native snapshots; runner reads and observation
return the typed `PresentedSession` described below.

`runner.observe_session(session_id, owner=...)` returns an async generator of
detached `PresentedSession` snapshots. Close it on disconnect, for example with
`contextlib.aclosing()`. Iteration validates access, subscribes before yielding the
initial snapshot, then delivers admission, native execution boundaries, tool starts,
artifact acceptance and final settlement. It stays open across turns. A late
subscriber starts with current state; there is no historical event replay.

Inside the registry, the active turn's `observation.messages` and `observation.usage` expose native
state at the observed boundaries. The retained capture references Pydantic AI's
history and usage during execution and detaches on settlement; it does not append
messages or accumulate usage. Internal snapshots are independent copies. Their derived
`snapshot.messages` and `last_turn` continue to select settled history. Tool returns
appear when the framework commits them to history, normally while preparing the
next model request; individual parallel results are not reconstructed early.
Provider-native search is visible in completed native responses, without separate
local execution notifications. Model execution remains non-streamed, without token
deltas.

Each session permits eight observers with 128 pending snapshots each, configured
in `app/agentic/config.py`. `ObservationLimitError` rejects excess observers;
`ObservationOverflowError` ends a slow observer explicitly without failing the
turn. Ownership and expiry are rechecked before delivery. An idle observer waits
for a conversation notification or the session's fixed expiry deadline, without
periodic wake-ups or duplicate snapshots. Expiry raises the same
`SessionNotFoundError` used by reads and never cancels admitted execution.
Disconnect/cancellation releases the observer slot and leaves execution alone.
Shutdown delivers queued settlement snapshots and ends observation; observing an
already closed runner yields one owner-checked snapshot and ends. Consumers must
still close generators when stopping iteration. The HTTP/SSE router used by the
demo is described below. Focused coverage:
`python -m pytest tests/test_pydantic_session_observation.py`.

`app.agentic.presentation.present_session(snapshot)` derives a complete typed
`PresentedSession` consumed by the frontend session controller. It selects session identity
and expiry, and one ordered `history` tuple. History contains native user-prompt
parts and `PresentedTurn` entries (`part_kind: "turn"`), rather than requiring
prompts to belong to turn groups. Each turn entry combines concise `lifecycle`
metadata (`run_id`, status and timestamps) with ordered
`parts`: `text`, `tool-call`, `builtin-tool-call`, plus application-owned `artifact`
parts. Consecutive activity for a run shares a group; an intervening visible prompt
starts another group without moving that prompt or inferring its turn ownership.
Both groups carry the same lifecycle; no frontend lookup in a separate `turns`
collection is needed. Lifecycle data is still stored only once internally.
Text includes only content and an optional
explicit `commentary`/`final_answer` phase; it does not infer finality. Tool activity
contains only name, call ID and status. Arguments, results, validation details,
instructions, application context, reasoning, usage and provider metadata stay
internal. This is field selection, not content redaction of model-authored text
or explicitly published artifacts.

Tool status uses native `success`, `failed`, `denied` and `interrupted` outcomes,
with `requested`/`running` while execution is active. A settled call with no result
is `interrupted`, without claiming whether it started or produced external effects.
Native retry prompts mark their associated call as failed without exposing details.
The OpenAI web-search adapter stores its explicit completion status inside native
return content; the projection selects that status without exposing the content.
Arbitrary local/MCP result text never determines status.

Accepted artifacts reuse `PublishedArtifact[ArtifactPayload]`, are detached and
appear immediately after the publishing call, even before a return is captured or
after turn failure/cancellation. This placement associates artifacts with their
calls; parallel calls need not publish artifacts in call order. Envelope `order`
remains the original publication order.

Projection reads the newest available cumulative native history, including active
execution, without retaining another history or accumulating usage. Native request
merging is accepted directly: user-prompt parts remain visible even when their
containing request has no run ID. There is no prompt index, prompt-to-turn
reconstruction or second application prompt store. Initial application context is
represented by native `TextContent` with application-only `metadata` identifying
its origin. The metadata survives native history merging/serialization and is not
sent to the model; presentation omits this content by its marker, never by matching
the text or counting its position. Visible prompt content preserves string input
or a sequence of textual fragments. Non-text input is outside this presentation.
Admission before native capture has lifecycle metadata only; setup failure before
prompt capture likewise has no presented prompt. A turn with no visible native
response has a turn entry with its lifecycle and empty `parts`, including admitted
work or setup failure without a run ID. Such entries retain admission order:
earlier unrepresented turns appear before the next represented turn, and remaining
ones appear at the end. Prompts keep their native order; these empty entries do
not establish prompt-to-turn attribution. HTTP/frontend integration must
account for this boundary. The runner applies this projection to both reads and
observation, exposing only `PresentedSession` to consumers. The registry's native
snapshots remain internal. Projection creates no retained history. The observation
wrapper closes the registry subscription on disconnect, cancellation or projection
failure, releasing observer capacity immediately. Ownership, expiry, overflow and
shutdown semantics remain unchanged. Focused coverage: `python -m pytest tests/test_pydantic_presentation.py`.

`app.agentic.http.create_session_router(registry_provider)` provides the native
HTTP boundary. The main application mounts it through the demo subapplication at
`/api/native`; tests also mount it with deterministic agents. The provider
returns configured names mapped to runners (or `None` for unavailable agents).
Application composition owns the shared agent and runner lifetimes. All routes
run asynchronously on the runner's event loop and require the existing
`X-Application-User: source:id` header.

Paths are relative to `/api/v1/agents/{configuration}/sessions`:

| Method | Path | Request / response |
| --- | --- | --- |
| POST | empty | `{initial_context?, artifact_capabilities?}`; 201 with session ID and expiry |
| GET | `/{session_id}` | Complete `PresentedSession` |
| POST | `/{session_id}/turns` | `{prompt}`; 202 with `{kind: "accepted"}` after admission |
| GET | `/{session_id}/events` | Session-level SSE with complete snapshots across turns |

Creation accepts generic JSON context and shared artifact capability declarations;
agent-specific domain input preparation remains composition work for cutover.
Execution limits stay server-owned. Prompts must be nonblank strings of at most
16,000 characters (`MAX_PROMPT_LENGTH`); their original whitespace is preserved.
Unknown request fields are rejected. FastAPI reports malformed bodies and headers
as 422 validation errors; invalid initialization detected by the runner (such as
oversized context or duplicate capability types) returns 400 `invalid_input`.

Submission combines prompt admission and execution startup; there is no separate
append endpoint, HTTP turn identifier or required native run ID in the acceptance
response. Execution can settle before the acknowledgement reaches the client;
202 confirms admission, while read/observation lifecycle state supplies the outcome.
Failed execution after admission does not change the acknowledgement into an HTTP
failure. There is no automatic retry or idempotency token.

The event stream acquires its subscription and initial snapshot before sending
headers. Unknown, expired and differently owned sessions all return 404 `unknown`;
unknown configuration returns 404 `unknown_configuration`, busy admission 409
`busy`, unavailable/closed runners 503 `agent_unavailable`, and excess observers
429 `observation_limit`. Reads and observation remain available on a closed runner
until expiry. Each SSE data frame is either `{kind: "snapshot", snapshot: ...}`
or `{kind: "error", reason: ...}`. After headers, expiry emits `unknown`, queue
overflow emits `observation_overflow`, and unexpected observation failure emits
`internal_error` without exception details. Errors end observation; turn completion
keeps it open for subsequent turns. Shutdown drains queued snapshots then closes.
EOF alone does not prove an active turn completed.

The response owns subscription cleanup even when sending headers/body fails or
the client disconnects. Disconnect never cancels admitted execution. Streaming
uses `Cache-Control: no-cache` and `X-Accel-Buffering: no`; there is no replay,
server-side reconnection, delta protocol, token streaming or periodic heartbeat.
The frontend controller reconnects after transient observation failures and consumes
a fresh snapshot.
OpenAPI describes both snapshot and error frame models under `text/event-stream`.
The generated frontend contract and demo use this boundary. Kochwiki composition
and removal of the legacy backend routes remain separate work. Focused coverage:
`python -m pytest tests/test_pydantic_http.py`.

The runner consumes background exceptions and logs failure exception types without
provider payloads. Existing conversation entries remain the only lifecycle records.
Caller cancellation while admission is pending cancels the pending execution. Once
admitted, execution remains runner-owned even if the submitting caller is cancelled
before `submit()` returns. Independent sessions can run concurrently, and session
expiry does not cancel admitted work.

`close()` rejects new sessions and submissions with `RunnerClosedError`. Owner-
checked `read_session()` remains available after shutdown, subject to session expiry,
so callers can inspect settled outcomes. Shutdown cancels outstanding
tasks and waits for native cleanup and conversation settlement. It is idempotent;
cancellation of the closing caller is propagated after cleanup finishes. Work
cancelled before admission creates no turn record and adds no prompt to history.
Cancellation after admission settles the existing record, possibly without a native
run ID if native execution has not started. Close the runner before leaving the
native agent context, as in the example. Cleanup is cooperative and has no additional
shutdown deadline; cancellation cannot roll back external tool effects.
There is no HTTP, SSE, frontend or production routing change.
Run `python -m pytest tests/test_pydantic_runner.py` for focused coverage.

Continuation passes native `message_history` without previous usage, so request
and tool budgets start fresh for every turn. The framework inherits conversation
identity from history and assigns a new run ID. Its native `Conversation` envelope
also carries cumulative usage and is deliberately not forwarded here; see
[native history and usage](https://pydantic.dev/docs/ai/core-concepts/message-history/).
The lower-level `execute_turn()` remains available for callers managing history
themselves. Native message JSON can be serialized and restored with
`ModelMessagesTypeAdapter` (convert the snapshot tuple to a list before serializing).
No hosted telemetry exporter is configured by this slice.

Pass a fresh `app.agentic.observation.TurnObservation` to
`execute_turn(..., observation=observation)` to retain inspection data on success,
failure or cancellation. Its `messages` are detached native `ModelMessage` objects,
including prior history, completed assistant text, confirmed tool results and any
native interrupted-request marker. `usage`, `run_id` and `conversation_id` identify
the execution. `started_calls` contains native `ToolCallPart` objects recorded at
the framework's pre-execution hook; it does not treat a model's requested call as
proof of execution. The capture is single-use and scoped to one invocation, so
concurrent turns on the same agent stay separate. Messages and usage are finalized
when `execute_turn` exits; started calls accumulate during execution.

Observation uses native lifecycle hooks with ordinary non-streamed `agent.run()`.
It does not install an event-stream handler, change dispatch or suppress failures.
A requested call with no start was not dispatched; a started call without a
confirmed return has an uncertain outcome after interruption. An explicit tool
failure retains native `outcome="failed"`. Feeding captured interrupted history
into a later turn lets Pydantic AI synthesize `outcome="interrupted"` results for
unanswered calls, preserving confirmed returns without replaying old calls. This
is history repair, not a guarantee that the model cannot choose another mutation.

These records are backend inspection data, including tool arguments and results.
The session presentation projects them into safe public parts for HTTP and SSE;
raw arguments and results remain internal. Run focused observation coverage with
`python -m pytest tests/test_pydantic_observation.py`.

Artifact publication is available independently through
`app.agentic.artifacts.create_artifact_toolset(capabilities, accept)`. Create it for
the current turn and pass it to `execute_turn(..., toolsets=[artifact_toolset])`;
run-scoped toolsets supplement the agent's existing tools, including MCP. The
toolset snapshots advertised capabilities and provides a native `present_artifact`
function tool with generated argument validation and capability instructions.
The input uses `ArtifactCandidate[ArtifactPayload]` directly; there is no separate
request model or conversion. Native tool arguments have this structure:

```json
{
  "candidate": {
    "type": "example",
    "payload": {
      "title": "Oats",
      "payload": {"name": "Oats"}
    }
  }
}
```

The inner `ArtifactPayload` also supports optional `subtitle` and `metadata`.
It rejects non-finite JSON values at the shared model boundary.
With no capabilities, it offers no tool. Presentation is core turn functionality,
so its schema is available eagerly rather than loaded on demand.

The synchronous, typed `accept` callback receives an `ArtifactSubmission` containing
the validated candidate and native run/tool-call IDs. Bind application session and
turn ownership in that callback; native IDs do not authorize access or replace
application turn IDs. The callback must atomically assign identity, timestamp and
ordering and retain the artifact before returning `ArtifactAccepted(artifact_id=...)`.
Capacity or other expected admission failures return `ArtifactRejected(reason=...)`
without retaining the candidate. Acceptance must not perform blocking I/O or schedule
background publication. `AgentConversation` supplies process-local acceptance
automatically; standalone execution can supply another callback. Production
sessions and the frontend are not connected yet.

Payload validation supports local JSON Schema references without network resolution.
Metadata validation additionally checks supported formats and treats omitted metadata
as an empty object when a metadata schema is advertised. Metadata is rejected without
an advertised schema. These capability/admission rejections become native failed
tool results through `ToolFailed`; malformed arguments use native validation and the
configured zero-retry budget, which ends the run. Successful results contain the
assigned ID, without echoing the artifact payload. The framework's sequential-tool
barrier orders publication before subsequent calls and model continuation.
Accepted artifacts belong to application storage and survive later model failure or
cancellation. Unexpected acceptance exceptions propagate without fabricated success;
the callback must avoid partially committing and then raising. No automatic replay
or duplicate-publication protection is added. Run focused coverage with
`python -m pytest tests/test_pydantic_artifacts.py`.

Execution defaults are collected in `app/agentic/config.py`: 40 model requests,
32 framework-counted tool calls, a 120-second
model-request deadline and a 60-second tool timeout. These are framework budgets,
not replicas of the legacy attempt counters. Automatic provider and validation
retries are disabled. Tools can report an expected failure with `ToolFailed`;
unexpected exceptions propagate. The model can still choose another call, so
these settings do not provide duplicate-mutation prevention.

Enable provider-native web search with `create_turn_agent(..., web_search=True)`.
Search is disabled by default. The eagerly available Pydantic AI `WebSearch()`
capability uses the provider's native implementation; no local search fallback,
custom search executor or extra dependency is installed. With the OpenAI Responses
model from `create_openai_model()`, OpenAI executes searches within its response.
Ordinary local tools and backend MCP tools remain available alongside search.

`MAX_NATIVE_TOOL_CALLS_PER_RESPONSE` defaults to 16. The OpenAI model factory sends
it as Responses `max_tool_calls` through the framework's `extra_body` setting;
this caps all provider-executed built-in calls in each response, separately from
the framework's local tool-call budget. The allowance resets for every response.
Together with the default 40 model requests, the normal run permits at most 640
built-in calls, rather than the legacy engine's separate 16-per-turn search limit.
OpenAI Responses does not support `WebSearch(max_uses=...)` in the pinned framework.
There is no custom turn-wide search counter or automatic search retry. Other
models supplied directly do not acquire this OpenAI-specific provider limit.
See the [Responses limit](https://developers.openai.com/api/reference/resources/responses/methods/create)
and [native tool support](https://pydantic.dev/docs/ai/tools-toolsets/native-tools/).

Native `NativeToolCallPart` and `NativeToolReturnPart` objects retain search
actions and provider status. They are present in observation messages and native
serialized history, but do not enter `started_calls`, which tracks local dispatch.
The OpenAI model factory requests search sources and preserves raw citation
annotations in `TextPart.provider_details["annotations"]`. These remain internal
inspection data; citation rendering is not added. Native history replay omits
source metadata that OpenAI does not accept as input and does not repeat searches.
The model may independently choose a new search when the capability is enabled.

A failed search item's provider status remains in the native return's `content`;
the framework does not translate it into local-tool `outcome="failed"`. Provider
request errors propagate with zero SDK retries. Earlier confirmed search activity
survives later failure. A response containing only search activity, with neither
an answer nor a function call, fails under the existing zero-output-retry policy.
There is no custom continuation loop. Deterministic HTTP transport coverage,
including local/MCP coexistence and follow-up history, runs with
`python -m pytest tests/test_pydantic_web_search.py`. The mocks verify request
configuration and native parsing, not live search quality or provider enforcement.
No live search was performed for this slice. Production wiring, streaming and
frontend handling remain unchanged.

After installing the backend dependencies, run the isolated live smoke test from
`backend` with `OPENAI_API_KEY` and `KOCHWIKI_OPENAI_MODEL` configured in `.env`:

```powershell
.venv/Scripts/python.exe -m scripts.verify_pydantic_turn
```

It uses a harmless local lookup tool and checks a follow-up without reexecuting
the tool. It prints the answers, call identities and usage without contacting MCP
or the application session API. Run deterministic coverage with
`python -m pytest tests/test_pydantic_turns.py`.

Native MCP access is configured with `app.agentic.mcp.create_mcp_toolset(url,
id="kochwiki")` and passed to `create_turn_agent(..., toolsets=[toolset])`.
The agent context owns connection setup and cleanup. An explicitly supplied
HTTP client remains caller-owned. Server instructions and discovered tool
schemas reach the model directly; domain tools load eagerly because they are
the agent's core functionality. There is no legacy registry, polling loop or
application reconnect policy in this path. Defaults in `app/agentic/config.py`
give MCP connection setup five seconds and reads 60 seconds.

Completed MCP tool errors become native failed tool results. Tool retries are
disabled, while transport failures propagate and do not add application-level
replays. A transport failure can surface during both the run and agent cleanup.
These policies do not prevent the model from independently choosing another
call. Native MCP regression tests exercise real protocol exchanges through an
in-process HTTP server, without model credentials or external domain access:

```powershell
python -m pytest tests/test_pydantic_mcp.py tests/test_pydantic_turns.py
```

For a real-model, read-only Kochwiki smoke test, configure all three Kochwiki
environment settings above and choose an existing tool explicitly advertised
with `readOnlyHint: true`:

```powershell
.venv/Scripts/python.exe -m scripts.verify_pydantic_mcp --tool TOOL_NAME --prompt "A question answerable with one call to this tool."
```

Only the selected tool is exposed. The script requires one successful result,
then requests a summary using native history with further tool execution
disabled. Read-only status is the server's declaration; choose a trusted lookup
tool. This verifies execution and history handoff, not answer quality. Neither
smoke script invokes the application session API.

The project skill in `.agents/skills/building-pydantic-ai-agents` is copied from
the installed framework package. Refresh that copy when upgrading Pydantic AI.

## Legacy engine: MCP connections and tool execution

The Kochwiki agent's model setting is `KOCHWIKI_OPENAI_MODEL`, replacing
`RECIPE_IMPROVEMENT_OPENAI_MODEL`. Rename that key in existing environment
configuration; the old name is no longer read.

Set optional `KOCHWIKI_OPENAI_REASONING_EFFORT` alongside the model name to
send `reasoning.effort` on every OpenAI response request. Leave it blank or
unset to use the selected model's default. The SDK accepts `none`, `minimal`,
`low`, `medium`, `high`, `xhigh`, and `max`; the selected model must support
the chosen value. For the example `gpt-6.1-sol` model, use `low`, `medium`,
`high`, `xhigh`, or `max` (default: `medium`). Unknown values fail settings
validation; model-specific unsupported values are rejected by OpenAI.

The production `kochwiki` agent still owns a generic MCP connection using the official Python
SDK (`mcp==2.2.0`). Set `KOCHWIKI_MCP_URL` to the complete Streamable HTTP
endpoint, for example `http://localhost:8002/mcp/` for a backend running on the
host. Inside Docker use an address reachable from the backend container,
such as `http://host.docker.internal:8002/mcp/`. The `demo` agent has no MCP
connections and remains available independently.

Each configured agent has an `AgentRuntime` that owns availability, MCP
connections and its optional model client. `ConfiguredAgents` delegates startup
and shutdown to those runtimes. Conversation services handle sessions and turns;
they do not own external connections. Runtime status is `created`, `connecting`,
`ready`, `unavailable`, `closing`, or `closed`, with a separate issue describing
the failure and whether it is retryable. All configured MCP connections are
mandatory; session creation, message appends and new turns return the existing
`503 agent_unavailable` until the runtime is ready. Existing session reads and
SSE observation remain accessible with the same ownership checks. Startup does
not wait for remote initialization, so a healthy
MCP server can still have a brief initial unavailable window.

The runtime owns a background repair task. Recognized transport and timeout
failures retry after `INITIAL_RETRY_SECONDS` in `app/mcp/config.py` (30 seconds),
measured after failed-attempt cleanup. Each attempt uses a fresh SDK client;
healthy connections, the agent and model client are retained. Missing local
configuration and unclassified initialization errors do not retry. Invalid initial
catalogues are cleared and rechecked on the catalogue polling schedule. Shutdown
settles backend-owned turns, then cancels pending attempts, polling or waits before
closing connections in reverse order and then the model client.
SDK contexts are entered and closed by their background owner task. Every cleanup
is attempted even if another fails.

Background initialization retrieves server instructions
and all pages of tool definitions. The connection stays open until shutdown.
The runtime polls server instructions and complete catalogues after `CATALOGUE_REFRESH_SECONDS` in
`app/mcp/config.py` (five minutes), measured after initialization or the previous
poll finishes. Polling bypasses the SDK response cache. Validated updates are
published together atomically; active turns keep their captured tools, instructions and mappings, and
subsequent turns use the updated catalogue. A successful empty catalogue is valid.
Any discovery or validation failure clears the affected catalogue and instructions and makes its
runtime unavailable. Polling continues and restores readiness once every required
catalogue is valid. Other connections and the session store are retained.
Instruction refresh requires modern MCP discovery (currently `2026-07-28`). It
sends a fresh `server/discover` request instead of using cached SDK instructions.
Absent instructions are valid and remove previous guidance. Legacy instruction
refresh is unsupported and makes polling fail. The SDK uses a 60-second read
timeout for tools and its own discovery timeout for server metadata.
Reconnect after readiness remains deferred; a broken
transport may consequently remain unavailable despite continued polling.

Each agent can own multiple MCP connections. Their configured names must be
unique within that agent. Every MCP tool is exposed to the model as
`<connection>__<tool>`, for example `kochwiki__search_foodstuffs`, and routed back
to the original server tool name. Generated names must contain only ASCII
letters, digits, underscores or hyphens and fit the model's 64-character limit.
Unsupported names or collisions in discovered tools disable the owning agent
at startup; names are never silently rewritten or truncated.

The generic `MCPToolset` adapts discovered input schemas into function tools with
`strict: false`, preserving optional fields and the server's validation contract.
The shared tool loop accepts one ordered `tool_sources` tuple. `LocalToolSource`
supplies locally registered tools, including artifact-producing tools, while
`MCPToolset` supplies artifact-free MCP tools through the same generic interface.
Each source contributes tools and instructions; an MCP source can itself contain
multiple connections. All tools share the existing call limits. Collisions across
sources or with local tool names are rejected before model generation.
Multiple function calls per model response are controlled by
`ALLOW_MULTIPLE_TOOL_CALLS` in `app/agents/config.py`, enabled by default. The service
executes them sequentially in response order under the shared limits, then returns
all results together in the next model request. Calls that need earlier tool
results to determine their arguments require separate model responses.
Server instructions include explicit mappings to model-facing tool names.
Source instructions appear once in configured source order, followed by local
agent instructions, which take precedence where they conflict. The Kochwiki
agent supplies its MCP tool source plus a session-specific presentation tool when
the caller advertises artifact capabilities. Local `register_recipe_proposal`,
recipe workflow instructions, presentation resolution and AI Service proposal
ownership have been removed. Its generic model turn strategy preserves snapshot, history,
turn reservation, failure, cancellation and expiration behavior. Turns allow 32
tool attempts and 40 provider responses. Artifact-free sources have no separate
artifact success limit; a successful MCP call does not count as a chat artifact.

Model agents can opt into hosted web search with `WebSearchConfig` passed to
`create_model_agent`; Kochwiki enables it using the existing configured model.
The model chooses when to search. Its separate default budget is sixteen hosted
calls per turn, including page-open/find actions. Each Responses request receives
the remaining allowance; after exhaustion, later requests omit search and can
continue with other tools. OpenAI executes searches internally. Completed or
failed search activity is retained as hosted tool history and shown through the
ordinary `web_search` timeline row, without local execution or fabricated results.
Returned search items and assistant messages are replayed, but full retrieved
page content is not guaranteed. Citation metadata remains internal and citation
rendering is deferred; this MVP has no search-specific public API or diagnostics.

Tool arguments must be a JSON object. MCP results are returned to the model as
JSON, preserving content blocks, structured content and the `isError` flag.
Transport/protocol failures return a generic tool failure so the model can respond;
the backend logs the connection, tool name and exception type. Cancellation
propagates normally. No automatic retries are performed for tool calls.
The generic adapter does not interpret domain payloads or create chat artifacts.
Kochwiki owns proposals and saving drafts. MCP results remain data for the model;
they do not automatically appear as artifacts. Model-backed sessions may separately
publish caller-advertised presentations through the local `present_artifact` tool.
Sessions retain an ordered internal history of messages, provider continuation
items, tool calls and exact returned results, accepted artifact records, and terminal
states. Later ordinary turns replay that context without invoking its tools.
Each message and tool call has one authoritative history record. Model input and
display messages are projections of those records; opaque reasoning is retained
separately as continuation context. Current replay includes previous-turn context.
Published artifacts derive their API `order` from the one-based position of their
artifact record in the full history. Values may have gaps; candidates have no
identity or order. The HTTP timeline projects user/final messages, intermediate assistant updates, tool calls with safe statuses,
embedded artifact envelopes, and failed-turn markers in recorded order. Active activity and accepted artifacts are visible immediately in session snapshots and SSE observation. Every complete message remains visible, including multiple final messages and final messages retained from failed turns.
Intermediate updates use only the provider's explicit `commentary` phase.
Supplied phases are preserved; absent or null phases remain absent and use the
primary assistant-message presentation. Phase never depends on later tool calls
or turn outcomes. They remain visible after
failed turns and are replayed to the model, but are excluded from the final-message
projection used for message limits and reconciliation. Only an explicit final-answer
message ends generation after successful provider completion and any tool execution.
Commentary, phase-less, empty, and continuation-only responses continue until
that message arrives or the provider-response limit fails the turn. The prompt asks
for brief progress explanations and a standalone final answer; opaque provider
reasoning remains internal.
Artifact tools return validated local candidates without mutating session state.
Orchestration checks capacity, assigns identity and timestamp, and records the
finalized tool result and artifact reference in history while storing the full
artifact in a session-owned map, atomically under the same lock. History alone
determines order and publication; the map holds content and expires with history.
There is no staging/publication step.
`agents/generation_history.py` interprets generation output as turn-history records.
The session store admits those records under its lock and owns lifecycle checks,
history updates, and notifications.
The conversation store retains no second text-message list or terminal-response
cache. Messages, message revision, and current terminal state are projected from
history; repeated failed-turn responses are reconstructed from terminal records.
Session metadata holds only expiry, initialization context, and settings, while
active reservations coordinate execution under the store lock.
`sessions/models/session.py` defines shared session and text-message contracts;
`sessions/config.py` defines message limits, observation settings, and the default session lifetime. The former standalone text store and
its conditional-append contract have been removed.
Unresolved calls receive explicitly service-generated reports distinguishing
execution never started from an unknown outcome; an unknown outcome may already
have completed and requires investigation before repeating a state-changing action.
Raw call arguments, results, and reasoning remain internal. The timeline exposes
only tool names, execution identities, and statuses. Explicit tool failure metadata
(including MCP `isError`) produces `failed`; arbitrary output text is never parsed
to infer failure. `completed` means a result returned without explicit failure,
not that a domain objective succeeded. Calls first display `requested`, then `running` once execution starts. Requested does not promise execution. Unresolved calls display `not_executed` or
`outcome_unknown` according to the retained service report.
There is no automatic rollback or duplicate-mutation prevention. Confirmed failed
turn requests remain cached; a later ordinary message starts a new turn.

`tests/test_mcp_connection.py` exercises a complete configured-agent tool turn
against Streamable HTTP servers with a scripted model, including proposal
creation followed by saving in a later turn and a failed save.
`tests/test_mcp_tools.py` covers multiple servers, routing, errors and limits.
Startup discovers capabilities but never invokes domain tools.

## Legacy conversation HTTP API

Every conversation request requires `X-Application-User: source:id`, including SSE observation. The value must contain exactly one colon and non-empty source and ID portions without whitespace. Prefixes are unrestricted; no user lookup or authentication is performed. Missing, empty, or malformed values return HTTP 422 with the typed `request_validation` envelope before conversation access or execution. Session creation stores the exact asserted identity as an immutable owner alongside the ephemeral session state. Reads, message submission, turn starts, and SSE observation check ownership before accessing conversation data or work. Another owner receives the same HTTP 404 `unknown` envelope as an unknown session, including before opening an SSE stream. An admitted turn continues against its original session when the caller disconnects or changes identity; ownership is never transferred. The demo frontend sends `demo:default`; Kochwiki hosts supply `kochwiki:<user-id>`.

Use `/api/v1/agents/{configuration}/sessions` with the fixed configurations
`kochwiki` and `demo`. Create with `POST` and an object envelope: Kochwiki uses
`{"input":{"context":{...}}}`; demo accepts `{}` or an empty
`input`. Read with `GET /{session_id}`, append a user message with
`POST /{session_id}/messages` and `{"text":"..."}`, then execute it with
`POST /{session_id}/turns`, which returns HTTP 202 with `{ "kind": "accepted", "turn_id": "..." }` after synchronous admission. A turn does not append a message. Backend-owned work continues when either request or observer disconnects; repeated starts for the current user message return the same turn identity without repeating execution.

Observe with `GET /{session_id}/turns/{turn_id}/events` (`text/event-stream`). The first typed `snapshot` event establishes retained safe state. Ordered `upsert` events contain full safe items, identity, zero-based position within the observed turn timeline and history sequence. Artifact items embed their complete public envelope, matching session reads; no separate upsert artifact field or registry lookup is needed. A typed `terminal` event supplies `completed`, `generation_failed`, or `conflict`. A typed stream `error` signals unavailable observation or exhausted observer capacity; transport EOF without terminal state also leaves the outcome unknown. Pre-stream errors keep typed HTTP envelopes. Session snapshots contain `session_id`, `expires_at`, `sequence`, and ordered `turns`. Each turn owns its ordered `timeline`, starting with its initiating user message, and contains `turn_id`, `user_message_id` and precise `status` (`pending`, `in_progress`, `closing`, `completed`, `generation_failed` or `conflict`). Top-level messages, artifacts and timeline collections are absent. The internal conversation snapshot uses the same nested presentation structure while retaining execution transcript/context and artifact storage separately. Pending work has an accepted user message but has not been admitted; retaining an explicitly final message on the admitted turn changes its status to closing. Terminal history takes precedence over final text. Closing and terminal stream events derive from that same snapshot after its timeline upserts, so terminal completion cannot skip final output. Closing does not promise success or completion; remaining work can still fail.

Subscription and initial capture share the store lock. Upserts covered by the initial snapshot are discarded; subsequent projection updates preserve tool identity and its original position. Observers are limited to eight per session and 128 queued projections each. Slow observers terminate without blocking work. Ten-second heartbeat checks detect session expiry without renewing its lifetime. There is no reconnect cursor, automatic reconnect, generation retry, or refresh recovery.

Verify incremental delivery through a running gateway with `python scripts/verify_timeline_gateway.py --base-url http://localhost:8000` (adjust the port). Response buffering is disabled per SSE response with `X-Accel-Buffering: no`; no proxy configuration change is required.
There is no individual artifact lookup route.

Model-backed sessions require an `input` object containing only `context`, which
must be a JSON object (an empty object is allowed). Nested JSON values retain
their types; non-finite numbers and non-JSON values are rejected. The serialized
model context, including its data-only prefix, is limited to 64,000 characters.
It is captured at creation and reused for every turn without being included in
session read responses. Domain validation and snapshot assembly belong to the
caller. The former `source`/`foodstuffs` input envelope is no longer accepted.

Sessions allow 200 messages of up to 16,000 characters each and model-backed
sessions allow 100 artifacts. The fixed 90-minute lifetime remains unchanged.
The OpenAI adapter consumes Responses API streams internally and returns only
confirmed completed responses. Each structurally valid completed output item is
retained immediately in immutable history before response completion. Failed,
incomplete, interrupted, or unfinished streams preserve those complete items,
while partial items are excluded and requested tools remain unexecuted. Each
assistant message is validated before retention; invalid messages fail generation
and are never replayed. The first explicit final message is the successful answer;
all other valid items remain retained without concatenation. Unexecuted requests receive service
execution reports during append-only failure cleanup. Provider streams close on success, failure, timeout, and
cancellation. The adapter allows 16,384 output tokens and a 120-second overall
deadline covering stream establishment and consumption per model response,
with the same network timeout and no automatic provider retries. These are individual request limits, not an overall turn
deadline; a multi-call turn can still exceed a gateway's request timeout.

Run the tests:

```powershell
pytest
```

## Legacy presentation capabilities

Model-backed session input accepts an optional `artifactCapabilities` array beside
`context`. Each entry supplies a unique `type`, a usage `description`, and a
`payloadSchema` JSON Schema object (draft 2020-12). These contracts are retained
for the session; renderer implementations remain in the frontend. Omit the array
or send an empty array for text-only sessions without the local presentation tool.

Capabilities may also supply `titleDescription` and `subtitleDescription` to
explain the intended header values. For a foodstuff display, these could require
the foodstuff name as the title and its brand as the subtitle, omitted when absent.
Provided descriptions must be nonblank and at most 2,000 characters. They are
passed to the agent as guidance, not used to validate generated header values.

```json
{
  "input": {
    "context": {},
    "artifactCapabilities": [{
      "type": "json",
      "description": "Show structured data when its structure helps the user.",
      "payloadSchema": {
        "type": "object",
        "properties": {"value": {}},
        "required": ["value"],
        "additionalProperties": false
      }
    }]
  }
}
```

The model receives capability descriptions and standalone schemas with a local
`present_artifact` tool accepting `type`, `title`, an optional `subtitle`, a complete
`payload`, and optional object `metadata`.
The subtitle is a short secondary label beneath the title, such as a brand.
It may be omitted or null; provided text must be nonblank and at most 200 characters.
The backend validates arguments and the selected payload schema before returning
an artifact candidate. Payload schemas can use local fragment references; external schema
references are rejected and validation never fetches schemas over the network.
Payload schema `format` annotations do not add format validation. Capabilities
can also advertise `metadataSchema`; metadata is validated separately, including
formats supported by the validator (such as UUID). Omission is validated as an
empty object. Metadata is rejected when no schema is advertised. Invalid arguments,
unsupported types, invalid payloads or metadata, and exhausted artifact limits return tool
errors. A successful call returns its artifact ID without echoing the payload.
Presentation shares the turn's tool-call budget and the session artifact limit.

Artifacts use the existing HTTP envelope, whose `payload` contains
`{"title": "...", "subtitle": <string or null>, "payload": <complete presentation data>, "metadata": <object or null>}`. IDs, order,
timestamps, and turn attribution are assigned by the conversation store. They
are retained once an artifact-producing tool returns its validated artifact, even
if later generation fails or is cancelled. Accepted artifacts are renderable immediately during the active turn. Failed-turn artifacts are available through session reads without
an assistant reply; candidates never returned or accepted leave no artifact state. Repeated turn reads return
the same artifacts projected from history. These retained artifacts continue consuming capacity.
History and payloads expire together after 90 minutes or disappear on restart.
Presentation
has no domain save effect. The AI Service does not know frontend renderers or
Kochwiki models, and MCP tool results remain independent of presentation.
# Test artifacts

Pytest stores its cache in `tests/.pytest_cache` and its `tmp_path` files in `tests/.pytest_tmp`. Both directories are disposable and ignored by Git and Docker. Pytest clears the base temporary directory at the start of each run; concurrent pytest runs in the same checkout can therefore interfere with each other.
