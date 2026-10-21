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
Kochwiki's Streamable HTTP endpoint, for example `http://localhost:8002/mcp/`
when running on the host, or `http://host.docker.internal:8002/mcp/` when the
backend container connects to a host service.
Optionally set `KOCHWIKI_OPENAI_REASONING_EFFORT`; leave it blank to use the
model's default. Settings validate the SDK's accepted values, while OpenAI
validates whether the selected model supports the requested effort.
In deployed environments, supply these values through the process environment or
secret store; never put a real key in tracked configuration. Missing or invalid
local Kochwiki configuration makes every Kochwiki session endpoint return
`503 agent_unavailable`. The deterministic demo remains available without model
credentials or Kochwiki access; its behavior is described below.
Kochwiki supplies all domain tools and workflow instructions through
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
deterministic demo and Kochwiki through the session HTTP API. The frontend's
`SessionController` consumes this API.

Kochwiki sessions use `/api/v1/agents/kochwiki/sessions`, with the contract described
below and OpenAPI at `/api/openapi.json`. Configuration or initialization failure
leaves that configuration unavailable (`503 agent_unavailable`) while the demo and
the rest of the application start normally. Correcting startup configuration
requires an application restart.

The demo subapplication is mounted at `/api/native`, with sessions at
`/api/native/api/v1/agents/demo/sessions` and its own OpenAPI document at
`/api/native/openapi.json`. It owns one shared `FunctionModel` agent and runner
for the application lifespan. Shutdown closes the runner before the agent.
Session initialization advertises the built-in `json` capability with a required
`value` field. Greeting labels are artifact titles, not separate capability types. The script uses `present_artifact` for two valid greeting artifacts
and one deliberate validation failure, then demonstrates a failed turn with
retained commentary and a subsequent successful turn. Script selection reads
the native history; it has no cross-session mutable step counter. No model
credentials, network model requests or Kochwiki access are needed.

`app.agentic.wiring.create_kochwiki_agent()` composes the agent from
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

Keep one agent context open across conversations to manage the model/provider
lifetime. Kochwiki uses Pydantic AI's `DynamicToolset` factory with
`per_run_step=False`: each turn creates and enters its own MCP toolset, and exit
closes that connection. Application startup makes no MCP requests. A connection
failure fails the admitted turn; a later turn opens a fresh connection and can
recover after the MCP server returns. Interrupted tool calls are not automatically
replayed. There is no application reconnect loop.
Pass `artifact_capabilities` to `AgentConversation` for
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
`conversation.last_settled_observation` returns detached `TurnObservation` inspection data.
Optional `initial_context` must be a JSON object. Creation validates and serializes
it once, preserving nested JSON types and rejecting non-finite numbers and cycles.
The serialized context, including its data-only prefix, is limited to 64,000
characters by `app/agentic/config.py`. Later caller mutations cannot change it.
It seeds a native user-data message, rather than system or agent instructions,
and follow-up turns reuse it through history without appending another copy.
Omission adds no context message; an explicit empty object is retained. Before
the first turn, `messages` exposes a detached context snapshot and `last_settled_observation`
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
publication order, including artifacts accepted during active execution.
They reuse the shared published-artifact envelope and retain the native tool-call
ID. Their `run_id` is the native run ID, which associates them with their
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
an internal process-local building block. The session registry adds authorization
and expiry; the presentation layer projects public history. Durable storage is
not implemented. Focused coverage runs with
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
Session IDs are distinct from native run/conversation IDs. `snapshot.last_settled_observation` and
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
`snapshot.messages` and `last_settled_observation` continue to select settled history. Tool returns
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

Accepted artifacts reuse `PublishedArtifact`, are detached and
appear immediately after the publishing call, even before a return is captured or
after turn failure/cancellation. This placement associates artifacts with their
calls; parallel calls need not publish artifacts in call order. The retained
artifacts tuple preserves publication order.

Projection reads the newest available cumulative native history, including active
execution, without retaining another history or accumulating usage. Native request
merging is accepted directly: user-prompt parts remain visible even when their
containing request has no run ID. Initial application context is
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
not establish prompt-to-turn attribution. The runner applies this projection to both reads and
observation, exposing only `PresentedSession` to consumers. The registry's native
snapshots remain internal. Projection creates no retained history. The observation
wrapper closes the registry subscription on disconnect, cancellation or projection
failure, releasing observer capacity immediately. Ownership, expiry, overflow and
shutdown semantics remain unchanged. Focused coverage: `python -m pytest tests/test_pydantic_presentation.py`.

`app.agentic.http.create_session_router(registry_provider)` provides the native
HTTP boundary. The main application uses it directly for Kochwiki and through
the demo subapplication at `/api/native`; tests also mount it with deterministic
agents. The provider
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

Creation accepts generic JSON context and artifact capability declarations.
Callers prepare domain-specific context before creating the session.
Execution limits stay server-owned. Prompts must be nonblank strings of at most
16,000 characters (`MAX_PROMPT_CHARACTERS`); their original whitespace is preserved.
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
The generated frontend contract, Kochwiki and demo use this boundary. Focused coverage:
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
Run `python -m pytest tests/test_pydantic_runner.py` for focused coverage.

Continuation passes native `message_history` without previous usage, so request
and tool budgets start fresh for every turn. The framework inherits conversation
identity from history and assigns a new run ID. Its native `Conversation` envelope
also carries cumulative usage and is deliberately not forwarded here; see
[native history and usage](https://pydantic.dev/docs/ai/core-concepts/message-history/).
The lower-level `execute_turn()` remains available for callers managing history
themselves. Native message JSON can be serialized and restored with
`ModelMessagesTypeAdapter` (convert the snapshot tuple to a list before serializing).
No hosted telemetry exporter is configured.

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
The input uses `ArtifactCandidate` directly. Tool arguments have this structure:

```json
{
  "type": "example",
  "content": {
    "title": "Oats",
    "payload": {"name": "Oats"}
  }
}
```

The inner `ArtifactContent` also supports optional `subtitle` and `metadata`.
It rejects non-finite JSON values at the shared model boundary.
With no capabilities, it offers no tool. Presentation is core turn functionality,
so its schema is available eagerly rather than loaded on demand.

The synchronous, typed `accept` callback receives an `ArtifactSubmission` containing
the validated candidate and native run/tool-call IDs. Bind application session and
run ownership in that callback; native IDs do not authorize access. The callback
must atomically assign identity and timestamp and append the artifact in publication order before returning `ArtifactAccepted(artifact_id=...)`.
Capacity or other expected admission failures return `ArtifactRejected(reason=...)`
without retaining the candidate. Acceptance must not perform blocking I/O or schedule
background publication. `AgentConversation` supplies process-local acceptance
automatically; standalone execution can supply another callback.

Payload and metadata validation support local JSON Schema references without network
resolution and check supported formats. Unknown formats are not enforced.
Metadata validation treats omitted metadata
as an empty object when a metadata schema is advertised. Metadata is rejected without
an advertised schema. These capability/admission rejections become native failed
tool results through `ToolFailed`; malformed arguments use native validation and the
configured zero-retry budget, which ends the run. Successful results contain the
assigned ID, without echoing the artifact payload. Result bodies contain no outcome
discriminator; native tool outcomes distinguish success from failure. The framework's sequential-tool
barrier orders publication before subsequent calls and model continuation.
Accepted artifacts belong to application storage and survive later model failure or
cancellation. Unexpected acceptance exceptions propagate without fabricated success;
the callback must avoid partially committing and then raising. No automatic replay
or duplicate-publication protection is added. Run focused coverage with
`python -m pytest tests/test_pydantic_artifacts.py`.

Execution defaults are collected in `app/agentic/config.py`: 40 model requests,
32 framework-counted tool calls, a 120-second
model-request deadline and a 60-second tool timeout. These are framework budgets.
Automatic provider and validation
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
built-in calls.
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
For Kochwiki, a per-run factory creates a fresh toolset and Pydantic AI owns its
connection setup and cleanup for that turn. A directly supplied static toolset
instead shares the agent context lifetime. An explicitly supplied HTTP client
remains caller-owned. Server instructions and discovered tool
schemas reach the model directly; domain tools load eagerly because they are
the agent's core functionality. Defaults in `app/agentic/config.py`
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

## Test artifacts

Pytest stores its cache in `tests/.pytest_cache` and its `tmp_path` files in `tests/.pytest_tmp`. Both directories are disposable and ignored by Git and Docker. Pytest clears the base temporary directory at the start of each run; concurrent pytest runs in the same checkout can therefore interfere with each other.
