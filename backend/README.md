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

## MCP connections and tool execution

The Kochwiki agent's model setting is `KOCHWIKI_OPENAI_MODEL`, replacing
`RECIPE_IMPROVEMENT_OPENAI_MODEL`. Rename that key in existing environment
configuration; the old name is no longer read.

The `kochwiki` agent owns a generic MCP connection using the official Python
SDK (`mcp==2.2.0`). Set `KOCHWIKI_MCP_URL` to the complete Streamable HTTP
endpoint, for example `http://localhost:8002/mcp/` for a backend running on the
host. Inside Docker use an address reachable from the backend container,
such as `http://host.docker.internal:8002/mcp/`. The `demo` agent has no MCP
connections and remains available independently.

Each configured agent has an `AgentRuntime` that owns availability, MCP
connections and its optional model client. `ConfiguredAgents` delegates startup
and shutdown to those runtimes. Conversation services handle sessions and turns;
they do not own external connections. A failed MCP startup disables the owning
agent and closes its resources. Shutdown first cancels and settles backend-owned turns with append-only cleanup, then closes connections in reverse order before the model client, attempting every cleanup even if one fails.

Application startup initializes the connection and retrieves server instructions
and all pages of tool definitions. The connection stays open until shutdown;
discovery is performed once, so restart the AI Service after changing tool
definitions or instructions. SDK requests use a 60-second read timeout.
Initialization/discovery failures are logged and make only the Kochwiki agent
unavailable. There is no automatic reconnect or catalogue refresh in this slice.

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
artifact references, and failed-turn markers in recorded order. Active activity and accepted artifacts are visible immediately in session snapshots and SSE observation. Every complete message remains visible, including multiple final messages and final messages retained from failed turns.
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
The conversation store retains no second text-message list or terminal-response
cache. Messages, message revision, and current terminal state are projected from
history; repeated failed-turn responses are reconstructed from terminal records.
Session metadata holds only expiry, initialization context, and settings, while
active reservations coordinate execution under the store lock.
`sessions/text_sessions.py` contains shared types and limits only; the former
standalone text store and its conditional-append contract have been removed.
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

## Conversation HTTP API

Every conversation request requires `X-Application-User: source:id`, including SSE observation. The value must contain exactly one colon and non-empty source and ID portions without whitespace. Prefixes are unrestricted; no user lookup or authentication is performed. Missing, empty, or malformed values return HTTP 422 with the typed `request_validation` envelope before conversation access or execution. Session creation stores the exact asserted identity as an immutable owner alongside the ephemeral session state. Reads, message submission, turn starts, and SSE observation check ownership before accessing conversation data or work. Another owner receives the same HTTP 404 `unknown` envelope as an unknown session, including before opening an SSE stream. An admitted turn continues against its original session when the caller disconnects or changes identity; ownership is never transferred. The demo frontend sends `demo:default`; Kochwiki hosts supply `kochwiki:<user-id>`.

Use `/api/v1/agents/{configuration}/sessions` with the fixed configurations
`kochwiki` and `demo`. Create with `POST` and an object envelope: Kochwiki uses
`{"input":{"context":{...}}}`; demo accepts `{}` or an empty
`input`. Read with `GET /{session_id}`, append a user message with
`POST /{session_id}/messages` and `{"text":"..."}`, then execute it with
`POST /{session_id}/turns`, which returns HTTP 202 with `{ "kind": "accepted", "turn_id": "..." }` after synchronous admission. A turn does not append a message. Backend-owned work continues when either request or observer disconnects; repeated starts for the current user message return the same turn identity without repeating execution.

Observe with `GET /{session_id}/turns/{turn_id}/events` (`text/event-stream`). The first typed `snapshot` event establishes retained safe state. Ordered `upsert` events contain full safe items, identity, zero-based timeline order, history sequence, and an accepted artifact envelope when needed. A typed `terminal` event supplies `completed`, `generation_failed`, or `conflict`. A typed stream `error` signals unavailable observation or exhausted observer capacity; transport EOF without terminal state also leaves the outcome unknown. Pre-stream errors keep typed HTTP envelopes. Session snapshots include `active_turn_id`, `active_turn_status` (`in_progress`, `closing`, or null when no turn is active), and `sequence` alongside terminal metadata. Retaining an explicitly final message changes the active status to `closing`; observers receive a typed `closing` event after its timeline upsert. This status does not promise success or completion; remaining work can still fail.

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

## Explicit presentation capabilities

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
