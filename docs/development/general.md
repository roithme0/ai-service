# General development

See [Change Validation](change-validation.md) for checks and test commands, and [Agentic Coding](agentic-coding.md) for AI-assisted workflows.

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

Open `http://localhost:4204` for the demo selector: **Conversation Visual Demo** (`/demos/conversation/visual`), **Conversation Live Demo** (`/demos/conversation/live`), **Image Generation Visual Demo** (`/demos/image-generation/visual`), or **Image Generation Live Demo** (`/demos/image-generation/live`). API requests proxy to port 8004. The conversation visual demo needs no model credentials or Kochwiki connection. The conversation live demo requires the [provider key and model](../operation.md#configuration); the image generation live demo requires the [provider key, model, and dedicated storage directory](../operation.md#configuration). The image visual demo runs locally with a predefined image and selectable failure scenarios; instructions do not change its image. Refresh or re-enter a conversation demo to start a new session.

For model-backed conversations or image generation, copy [backend/.env.example](../../backend/.env.example) to `backend/.env` and configure the [required settings](../operation.md#configuration). Restart the backend after configuration changes. Interactive API documentation is at `http://localhost:8004/api/docs`.

### Container alternative

Copy [deployment/.env.example](../../deployment/.env.example) to `deployment/.env`. From the **repository root**:

```powershell
docker compose --env-file deployment/.env -f deployment/docker-compose-local.yml up --build
```

Open `http://localhost:8000` (or the configured `GATEWAY_PORT`). Containers have no source reload. Rebuild after changes. Follow backend logs with the same Compose command prefix and `logs -f backend`.

## Frontend scripts

Run `npm run <script>` from **frontend/** after `npm ci`. Common scripts in [package.json](../../frontend/package.json) include:

- `start:app`, `build:app`, and `watch:app` run or build the app. See [chat UI development](#develop-the-chat-ui-package) and [image generation development](#develop-the-image-generation-package) for library commands.
- `generate:image-generation-contract` and `check:image-generation-contract` update or verify the image generation contract; see [generated contracts](#update-generated-contracts) for all contracts and prerequisites.
- `test:app` and `test:image-generation` run focused test groups; browser tests require Playwright Chromium. See [validation](change-validation.md) for the full suite.
- `format:changed`, `lint`, and `lint:fix` format or lint frontend and shared tooling changes.
- `ng` forwards arguments to the Angular CLI.

## Update generated contracts

Install backend and frontend dependencies first. From **frontend/**:

```powershell
$env:PYTHON = (Resolve-Path ../backend/.venv/Scripts/python.exe).Path
npm run generate:conversation-contract
npm run check:conversation-contract
npm run generate:transcription-contract
npm run check:transcription-contract
npm run generate:image-generation-contract
npm run check:image-generation-contract
```

Generators produce TypeScript types and Zod validators from backend schemas without starting the application. Manual commands use `PYTHON` when set or Python on PATH; automated validation selects the repository virtual environment explicitly. Check commands compare generated output without modifying checked-in files. Ship backend schema changes, generated files, and frontend consumers together. Review generated changes; do not edit them by hand.

## Develop the chat UI package

From **frontend/**, run `npm run build:chat-ui`, then `npm run watch:chat-ui`. In the sibling **kochwiki-v2/frontend/** checkout, run `npm run link:chat-ui` and `npm start`. Reinstalling Kochwiki dependencies replaces the local link; link again when needed. CI and Docker use the published package.

See the [package README](../../frontend/projects/chat-ui/README.md) for component integration, themes, and renderers.

### Package and browser checks

From **frontend/**, run `npm run build:chat-ui`, then `node scripts/check-chat-ui-package.mjs`. This verifies built exports, runtime behavior, explicit application identity, and strict consumer declarations without workspace aliases.

For manual layout and interaction checks, use [Conversation Visual Demo](http://localhost:4204/demos/conversation/visual) with the [local servers](#run-locally) running. Check narrow viewports, scrolling, artifact expansion, and keyboard submission in Chrome and Firefox. Refresh to restart the scripted session.

## Develop the image generation package

After `npm ci`, build the standalone image generation package from **frontend/** with `npm run build:image-generation`, then verify its packed controller entrypoint and declarations with `npm run check:image-generation-package`. Use `npm run pack:image-generation` to build and create a package archive.

Run its focused tests from the **repository root** with `node .agents/validation/test.mts --group image-generation` after completing [local setup](#run-locally). Pass a file or case filter after `--` for targeted checks.

## Evaluate conversation tool use

Complete [local setup](#run-locally), including the editable backend Python 3.13 environment with `test` and `dev` extras, and configure the [conversation Live Demo provider key and model](../operation.md#configuration) in the environment or `backend/.env`. From the **repository root**, run:

```powershell
node .agents/validation/run.mts --group evals
```

For tests only, use `node .agents/validation/test.mts --group evals`. Each invocation runs the single case afresh against the real model, making paid requests, and writes its report and execution log to a unique directory under `.codex-validation/evals/manual/`. The console shows the report location and available result, model, reasoning, and tool-call evidence. Exit 1 indicates behavioral failure and exit 2 an execution error in the underlying evaluator; centralized commands fail for either or for orchestration errors. Missing credentials are an execution error, not a skip.

Default validation, `non-e2e`, tooling groups, and hooks exclude evaluations. Explicit `--group all` includes evaluations and E2E. Native runner arguments are not supported for `evals`. The standalone module also accepts a caller-selected `--report` path.

CI runs this evaluation as a blocking publication gate using the Live Demo configuration. Missing credentials, including on fork pull requests, fail the gate. When the evaluation step fails, download `evals-diagnostics` for available reports and logs; artifacts are retained for seven days. A setup failure may prevent report creation. The single explicit greeting attempt does not establish general tool-selection reliability and provider outages can block publication. See the [case and evaluator](../../backend/app/evals/conversation_tool_use.py) and [Pydantic Evals documentation](https://ai.pydantic.dev/evals/).
