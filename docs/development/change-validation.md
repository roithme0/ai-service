# Change Validation

See the [frontend test guidance](frontend-testing.md#frontend-test-guidance) and [backend test guidance](backend-testing.md#backend-test-guidance) when designing coverage.

Use applicable formatting and lint checks, then select the test files or cases covering the change. For a full manual run, complete [local setup](general.md#run-locally) for both backend and frontend and [install Playwright Chromium](#end-to-end-browser-tests). From the **repository root**:

```powershell
node .agents/validation/run.mts
```

This formats changed files, lints, checks freshness of all generated contracts, and runs the default test groups, including browser components. Live evaluations and E2E are excluded. Formatting includes staged, unstaged, and untracked changed files; review unrelated edits first and inspect the resulting diff. `--scope frontend|backend` limits formatting and lint only; `--no-format` skips formatting. Contract checks run regardless of scope or test group.

Validation uses Python 3.13 from `backend/.venv` with the `test` and `dev` extras, frontend npm dependencies, and Playwright Chromium. No running application, Docker, or secrets are needed. See [generated contracts](general.md#update-generated-contracts) for manual freshness checks.

For tests only, use `node .agents/validation/test.mts` from the **repository root**. Discover groups with `--list` and select them with repeated `--group NAME`. The `tooling` group requires both ecosystems; `tooling-frontend` needs no Python. `tooling-e2e` mocks orchestration; actual E2E has [separate prerequisites](#end-to-end-browser-tests). See the [runner](../../.agents/validation/test.mts) for native argument forwarding and individual-file selection.

For focused backend tests, select `--group backend`; for frontend tests, select `--group frontend-app` or `--group chat-ui`. Pass a file or case filter after `--` for targeted checks. Use the backend virtual environment's Black in your editor to match [the project settings](../../backend/pyproject.toml).

Container alternative, from the **repository root**:

```powershell
docker compose -f deployment/tests/backend/compose.yml up --build --abort-on-container-exit --exit-code-from backend-tests
```

For build verification, run `npm run build:app` and `npm run build:chat-ui` from **frontend/**. Test locations are listed in [navigation](../navigation.md#find-related-tests).

With Docker running, run the [gateway regression tests](../../deployment/tests/gateway/test_timeout.py) from the **repository root**:

```powershell
docker compose -f deployment/tests/gateway/compose.yml up --abort-on-container-exit --exit-code-from gateway-tests
```

## Component browser tests

From **frontend/**, run `npm run test:chat-ui:browser` after installing Playwright Chromium. It uses Vitest Browser Mode with Playwright and Angular TestBed for `*.browser.spec.ts` tests; the default jsdom run excludes these files. No backend or Docker is needed.

## End-to-end browser tests

[Playwright](../../frontend/playwright.config.ts) tests live in [frontend/e2e/](../../frontend/e2e/). Start the [Docker stack](general.md#container-alternative) separately. The default target is `http://localhost:8000`. From **frontend/**, after `npm ci`:

```powershell
npx playwright install chromium
npx playwright test
npx playwright codegen http://localhost:8000
```

Install Chromium on first setup and after Playwright upgrades. Codegen records tests interactively; save reviewed tests as `e2e/<name>.spec.ts` and use `page.goto('/')` for the configured target. Add `--headed` to test runs to watch the browser.

For an already-running dev server (or a custom gateway URL):

```powershell
$env:PLAYWRIGHT_BASE_URL = 'http://localhost:4204'
npx playwright test --headed
Remove-Item Env:PLAYWRIGHT_BASE_URL
```

Codegen takes its URL explicitly. Results and failure traces go to gitignored `e2e/test-results/`, replaced on each run. Current coverage checks landing-page links. Run `node .agents/validation/e2e.mts` from the repository root for browser flow, frontend/backend integration, or local deployment changes. It updates Docker using the build cache and runs Playwright. The stack stays running; logs are in `.codex-validation/e2e/`.

The [CI workflow](../../.github/workflows/publish-app.yml) defines validation, image testing, and publication dependencies. The isolated runner writes browser results and HTML reports under separate `.codex-validation/e2e/manual/playwright-*/` directories. On failure, the `e2e-diagnostics` artifact contains available results and reports with their run directories preserved, along with top-level manual logs.
