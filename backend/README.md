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

The backend installs Kochwiki's shared Pydantic contract package from a GitHub
Release wheel, pinned by URL and SHA-256 in `pyproject.toml`. Development, CI,
and Docker use the same dependency. To upgrade, select a release from
[Kochwiki Releases](https://github.com/roithme0/kochwiki-v2/releases), update the
URL and checksum using its `SHA256SUMS`, and run the snapshot validation
checks. The pin verifies the artifact; compatibility with the deployed Kochwiki
API still requires coordinated validation.

Initialization snapshots retain decimal values internally and serialize them
for model context. Snapshot validation still uses Kochwiki's shared unit contract.

Run the development server:

```powershell
fastapi dev app/main.py
```

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
The frontend simulates a 405 compatibility error on the next message after completion; the backend still accepts further submissions. Refresh the page to restart with a new session.
The generator receives the conversation and the existing recipe and foodstuff
snapshots. Kochwiki supplies all domain tools and workflow instructions through
MCP; the AI Service supplies only generic conversational guidance.

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
agent and closes its resources. Shutdown closes connections in reverse order
before the model client, attempting every cleanup even if one fails.

Application startup initializes the connection and retrieves server instructions
and all pages of tool definitions. The connection stays open until shutdown;
discovery is performed once, so restart the AI Service after changing tool
definitions or instructions. SDK requests use a ten-second read timeout.
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
agent supplies only its MCP tool source: local `register_recipe_proposal`, recipe
workflow instructions, presentation resolution and AI Service proposal ownership
have been removed. Its generic model turn strategy preserves snapshot, history,
turn reservation, failure, cancellation and expiration behavior. Turns allow six
tool attempts and eight provider responses. Artifact-free sources have no separate
artifact success limit; a successful MCP call does not count as a chat artifact.

Tool arguments must be a JSON object. MCP results are returned to the model as
JSON, preserving content blocks, structured content and the `isError` flag.
Transport/protocol failures return a generic tool failure so the model can respond;
the backend logs the connection, tool name and exception type. Cancellation
propagates normally. No automatic retries are performed for tool calls.
The generic adapter does not interpret domain payloads or create chat artifacts.
Kochwiki owns proposals and saving drafts. This slice presents results in text;
Kochwiki turns and session reads have empty artifact lists. Generic artifact
handling remains a later slice. Only final replies are retained between turns,
not tool transcripts, so generic guidance asks the model to include identifiers
needed for follow-up actions. There is no automatic rollback of MCP writes if
later model generation fails. Failed turns are retained by the session lifecycle
and are not replayed on a repeated turn request.

`tests/test_mcp_connection.py` exercises a complete configured-agent tool turn
against Streamable HTTP servers with a scripted model, including proposal
creation followed by saving in a later turn and a failed save.
`tests/test_mcp_tools.py` covers multiple servers, routing, errors and limits.
Startup discovers capabilities but never invokes domain tools.

## Conversation HTTP API

Use `/api/v1/agents/{configuration}/sessions` with the fixed configurations
`kochwiki` and `demo`. Create with `POST` and an object envelope: Kochwiki uses
`{"input":{"source":...,"foodstuffs":...}}`; demo accepts `{}` or an empty
`input`. Read with `GET /{session_id}`, append a user message with
`POST /{session_id}/messages` and `{"text":"..."}`, then execute it with
`POST /{session_id}/turns`. A turn does not append a message. Session reads and
completed turns return published artifacts with shared identity and typed payloads.
There is no individual artifact lookup route.

Run the tests:

```powershell
pytest
```
