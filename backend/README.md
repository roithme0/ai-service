# AI Service Backend

Minimal FastAPI backend for the AI Service.

## Local development

Create and activate a virtual environment, then install the project:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
```

Run the development server:

```powershell
fastapi dev app/main.py
```

To enable the recipe-improvement agent, copy `.env.example` to `.env` and set
`OPENAI_API_KEY`, `RECIPE_IMPROVEMENT_OPENAI_MODEL`, and `KOCHWIKI_BASE_URL`.
The backend loads this ignored file automatically. The URL identifies Kochwiki's
API base for resolving validated recipe candidates into authoritative presentations.
In deployed environments, supply these values through the process environment or
secret store; never put a real key in tracked configuration. Missing or invalid
local recipe configuration makes every Kochwiki session endpoint return
`503 agent_unavailable`. The deterministic demo HTTP configuration remains available
without model credentials or Kochwiki access. The frontend now uses this demo:
any text advances its greeting, real greeting-tool artifact, and completion sequence.
Refresh the page to restart with a new session; further submissions remain accepted.
The generator receives the conversation, recipe and available-foodstuff snapshots,
and versioned recipe-specific instructions. It may register validated recipe
proposals through the bounded tool-call flow before returning its reply.

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
