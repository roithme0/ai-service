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

Open `http://localhost:4204` for the demo selector: **Visual Demo** (`/demos/visual`) or **Live Demo** (`/demos/live`). API requests proxy to port 8004. Visual Demo needs no model credentials or Kochwiki connection; Live Demo requires the [provider key](operation.md#configuration). Refresh or re-enter a demo to start a new session.

For model-backed conversations, copy [backend/.env.example](../backend/.env.example) to `backend/.env` and configure the [agent settings](operation.md#configuration). Restart the backend after configuration changes. Interactive API documentation is at `http://localhost:8004/api/docs`.

### Container alternative

Copy [deployment/.env.example](../deployment/.env.example) to `deployment/.env`. From the **repository root**:

```powershell
docker compose --env-file deployment/.env -f deployment/docker-compose-local.yml up --build
```

Open `http://localhost:8004` (or the configured `GATEWAY_PORT`). Containers have no source reload; rebuild after changes. Follow backend logs with the same Compose command prefix and `logs -f backend`.

## Validate changes

Complete [local setup](#run-locally) for both backend and frontend, then [install Playwright Chromium](#end-to-end-browser-tests). From the **repository root**:

```powershell
node .agents/validation/run.mts
```

This formats changed files, lints, checks freshness of both generated contracts, and runs all non-E2E tests, including browser components. Formatting includes staged, unstaged, and untracked changed files; review unrelated edits first and inspect the resulting diff. `--scope frontend|backend` limits formatting and lint only; `--no-format` skips formatting. Contract checks run regardless of scope or test group.

Validation uses Python 3.13 from `backend/.venv` with the `test` and `dev` extras, frontend npm dependencies, and Playwright Chromium. No running application, Docker, or secrets are needed. See [generated contracts](#update-generated-contracts) for manual freshness checks.

For tests only, use `node .agents/validation/test.mts` from the **repository root**. Discover groups with `--list` and select them with repeated `--group NAME`. The `tooling` group requires both ecosystems; `tooling-frontend` needs no Python. `tooling-e2e` mocks orchestration; actual E2E has [separate prerequisites](#end-to-end-browser-tests). See the [runner](../.agents/validation/test.mts) for native argument forwarding and individual-file selection.

For focused backend tests, select `--group backend`; for frontend tests, select `--group frontend-app` or `--group chat-ui`. Focused runs do not replace full validation. Use the backend virtual environment's Black in your editor to match [the project settings](../backend/pyproject.toml).

Container alternative, from the **repository root**:

```powershell
docker compose -f deployment/tests/backend/compose.yml up --build --abort-on-container-exit --exit-code-from backend-tests
```

For build verification, run `npm run build:app` and `npm run build:chat-ui` from **frontend/**. Test locations are listed in [navigation](navigation.md#find-related-tests).

With Docker running, run the [gateway regression tests](../deployment/tests/gateway/test_timeout.py) from the **repository root**:

```powershell
docker compose -f deployment/tests/gateway/compose.yml up --abort-on-container-exit --exit-code-from gateway-tests
```

### Component browser tests

From **frontend/**, run `npm run test:chat-ui:browser` after installing Playwright Chromium. It uses Vitest Browser Mode with Playwright and Angular TestBed for `*.browser.spec.ts` tests; the default jsdom run excludes these files. No backend or Docker is needed.

### End-to-end browser tests

[Playwright](../frontend/playwright.config.ts) tests live in [frontend/e2e/](../frontend/e2e/). Start the [Docker stack](#container-alternative) separately; the default target is `http://localhost:8004`. From **frontend/**, after `npm ci`:

```powershell
npx playwright install chromium
npx playwright test
npx playwright codegen http://localhost:8004
```

Install Chromium on first setup and after Playwright upgrades. Codegen records tests interactively; save reviewed tests as `e2e/<name>.spec.ts` and use `page.goto('/')` for the configured target. Add `--headed` to test runs to watch the browser.

For an already-running dev server (or a custom gateway URL):

```powershell
$env:PLAYWRIGHT_BASE_URL = 'http://localhost:4204'
npx playwright test --headed
Remove-Item Env:PLAYWRIGHT_BASE_URL
```

Codegen takes its URL explicitly. Results and failure traces go to gitignored `e2e/test-results/`, replaced on each run. Current coverage checks landing-page links. Run `node .agents/validation/e2e.mts` from the repository root for browser flow, frontend/backend integration, or local deployment changes. It updates Docker using the build cache and runs Playwright. The stack stays running; logs are in `.agents/.codex-validation/e2e/`.

The [CI workflow](../.github/workflows/publish-app.yml) defines validation, image testing, and publication dependencies. The isolated runner writes browser results and HTML reports under separate `.agents/.codex-validation/e2e/manual/playwright-*/` directories. On failure, the `e2e-diagnostics` artifact contains available results and reports with their run directories preserved, along with top-level manual logs.

## Update generated contracts

Install backend and frontend dependencies first. From **frontend/**:

```powershell
$env:PYTHON = (Resolve-Path ../backend/.venv/Scripts/python.exe).Path
npm run generate:conversation-contract
npm run check:conversation-contract
npm run generate:transcription-contract
npm run check:transcription-contract
```

Generators produce TypeScript types and Zod validators from backend schemas without starting the application. Manual commands use `PYTHON` when set or Python on PATH; automated validation selects the repository virtual environment explicitly. Check commands compare generated output without modifying checked-in files. Ship backend schema changes, generated files, and frontend consumers together. Review generated changes; do not edit them by hand.

## Develop the chat UI package

From **frontend/**, run `npm run build:chat-ui`, then `npm run watch:chat-ui`. In the sibling **kochwiki-v2/frontend/** checkout, run `npm run link:chat-ui` and `npm start`. Reinstalling Kochwiki dependencies replaces the local link; link again when needed. CI and Docker use the published package.

See the [package README](../frontend/projects/chat-ui/README.md) for component integration, themes, and renderers.

### Package and browser checks

From **frontend/**, run `npm run build:chat-ui`, then `node scripts/check-chat-ui-package.mjs`. This verifies built exports, runtime behavior, explicit application identity, and strict consumer declarations without workspace aliases.

For manual layout and interaction checks, use [Visual Demo](http://localhost:4204/demos/visual) with the [local servers](#run-locally) running. Check narrow viewports, scrolling, artifact expansion, and keyboard submission in Chrome and Firefox. Refresh to restart the scripted session.

## AI-assisted development

| Resource | Purpose |
| --- | --- |
| [AGENTS.md](../AGENTS.md) | Coding rules, approval boundaries, and required validation. |
| [Skills](../.agents/skills/) | Reusable workflows, including concept, spec, delivery, review, and Pydantic AI guidance. Read the relevant `SKILL.md` before use. |
| [Validation](../.agents/validation/) | Shared checks used by manual commands, CI, and agent hooks. |
| [Hooks](../.codex/hooks.json) | Codex adapter snapshots content before prompts and validates affected scopes on stop. |
| [Project configuration](../.codex/config.toml) | Angular CLI and OpenAI documentation MCP connections. |

Review and trust hooks before relying on them. Relevant hooks perform [validation](#validate-changes), including both contract freshness checks; unchanged discussion turns run none. Their commands invoke Node.js using absolute checkout paths; run validation manually if unavailable. Hook state and reports are gitignored under `.agents/.codex-validation/`.

Temporary concepts, specs, and plans belong under `.agents/`, outside commits and permanent documentation. Invoke spec and delivery workflows explicitly; routine changes do not require them.
