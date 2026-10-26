# Development

## Prerequisites

- Python 3.13 and Node.js 24 for host development; Docker with Compose v2 for containers.
- Commands below use PowerShell. Use `npm.cmd` if PowerShell blocks `npm.ps1`.
- Keep credentials in ignored `.env` files; tracked examples contain placeholders.

## Run locally

From **backend/**:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test,dev]"
python -m uvicorn app.main:app --reload --port 8004
```

In another terminal, from **frontend/**:

```powershell
npm ci
npm run start:app
```

Open `http://localhost:4204`; API requests proxy to port 8004. The [Visual Demo](../backend/app/demos/visual_conversation_demo/) uses the `visual-demo` agent configuration and needs no model credentials or Kochwiki connection. Refresh to start a new session.

For the model-backed agent, copy [backend/.env.example](../backend/.env.example) to `backend/.env` and configure the [Kochwiki settings](operation.md#configuration). Restart the backend after configuration changes. Interactive API documentation is at `http://localhost:8004/api/docs`.

### Container alternative

Copy [deployment/.env.example](../deployment/.env.example) to `deployment/.env`. From the **repository root**:

```powershell
docker compose --env-file deployment/.env -f deployment/docker-compose-local.yml up --build
```

Open `http://localhost:8004` (or the configured `GATEWAY_PORT`). Containers have no source reload; rebuild after changes. Follow backend logs with the same Compose command prefix and `logs -f backend`.

## Validate changes

Format changed backend Python files from the **repository root**:

```powershell
node .codex/validation/backend.mts --format
```

Then, from **backend/**, with its virtual environment active:

```powershell
python -m pytest
```

Use the backend virtual environment's Black in your editor to match the version and settings in `backend/pyproject.toml`. Formatting includes staged, unstaged, and untracked changed files; review unrelated edits first.

Container alternative, from the **repository root**:

```powershell
docker compose -f deployment/tests/backend/compose.yml up --build --abort-on-container-exit --exit-code-from backend-tests
```

From **frontend/**, run in order after frontend edits. Formatting includes staged, unstaged, and untracked files; review unrelated edits first.

```powershell
npm run format:changed
npm run lint
npm run test:tooling
npm run test:app
npm run test:chat-ui
```

For build verification, run `npm run build:app` and `npm run build:chat-ui`. Test locations are listed in [navigation](navigation.md#find-related-tests).

The [gateway regression harness](../deployment/tests/gateway/) currently mounts `deployment/nginx.conf`, while the configuration lives at `deployment/gateway/nginx.conf`. Correct that mount before relying on this check.

## Update the conversation contract

Install backend and frontend dependencies first. From **frontend/**:

```powershell
$env:PYTHON = (Resolve-Path ../backend/.venv/Scripts/python.exe).Path
npm run generate:conversation-contract
npm run check:conversation-contract
```

The generator exports the session router's OpenAPI document without starting agents, then produces TypeScript types and Zod validators. Ship backend schema changes, generated files, and frontend consumers together. Review generated changes; do not edit them by hand.

## Develop the chat UI package

From **frontend/**, run `npm run build:chat-ui`, then `npm run watch:chat-ui`. In the sibling **kochwiki-v2/frontend/** checkout, run `npm run link:chat-ui` and `npm start`. Reinstalling Kochwiki dependencies replaces the local link; link again when needed. CI and Docker use the published package.

See the [package README](../frontend/projects/chat-ui/README.md) for component integration, themes, and renderers.

### Package and browser checks

From **frontend/**, run `npm run build:chat-ui`, then `node scripts/check-chat-ui-package.mjs`. This verifies built exports, runtime behavior, explicit application identity, and strict consumer declarations without workspace aliases.

With the [local servers](#run-locally) running, open `http://localhost:4204` at a portrait-phone viewport:

- Submit arbitrary text through the introduction, two JSON artifacts (`visual-demo.greeting` and `visual-demo.greetings`, with 30 greetings), invalid publication, scripted failure, and completion guidance. The error's demo action is intentionally inert.
- Expand/collapse the long artifact and run details; check retained content after failure and scroll position during toggles. Native final-answer anchoring still needs Chrome/Firefox verification.
- Send one more message to trigger the frontend-only 405 compatibility error without retry. Refresh to restart; there is no restart button.
- Check history/composer placement during viewport changes, no horizontal overflow, Enter/send submitting once, and Shift+Enter adding a line break.

## AI-assisted development

| Resource | Purpose |
| --- | --- |
| [AGENTS.md](../AGENTS.md) | Coding rules, approval boundaries, and required validation. |
| [Skills](../.agents/skills/) | Reusable workflows, including concept, spec, delivery, review, and Pydantic AI guidance. Read the relevant `SKILL.md` before use. |
| [Hooks](../.codex/hooks.json) | Snapshot frontend and backend content before prompts; validate affected scopes on stop. |
| [Project configuration](../.codex/config.toml) | Angular CLI and OpenAI documentation MCP connections. |

Review and trust hooks before relying on them. Their commands use PowerShell and absolute checkout paths; run validation manually if unavailable. Reports live under `frontend/.codex-validation/` and `backend/.codex-validation/`. Review formatting changes before completion.

Temporary concepts, specs, and plans belong under `.agents/`, outside commits and permanent documentation. Invoke spec and delivery workflows explicitly; routine changes do not require them.
