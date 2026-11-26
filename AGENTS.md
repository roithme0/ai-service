# Agents Guide

## Coding Rules

- No destructive commands.
- Strict typing is required. Avoid `Any` and untyped parameters/returns.
- Keep code comments to a minimum; avoid commenting the obvious.

## AI Workflow

- If a user message is phrased as a question, answer it in chat first and ask for explicit confirmation before making code or file changes.
- Confirm before touching build or tooling config.
- Summarize changes and call out risks.
- Treat backend APIs and published UI packages as contracts for consuming applications. Ship contract changes with generated types and affected in-repo consumers; make breaking changes explicit. Preserve legacy compatibility only when explicitly required.

### Testing

- Add unit, component, integration, or contract tests where they provide meaningful regression protection. Choose the smallest scope that verifies the behavior. Use a real browser when the behavior depends on layout or native browser interactions. Avoid tests that merely restate implementation details.
- Follow the [frontend test guidance](docs/development/frontend-testing.md#frontend-test-guidance) for required frontend coverage, layers, and conventions.
- Create new end-to-end tests only when explicitly requested. Maintain and repair existing end-to-end tests as needed, preserving their regression coverage.
- Remove existing tests only when redundant, obsolete, flaky, or blocking legitimate refactoring; explain the reason.

## Temporary AI Artifacts

- Store implementation-specific concepts, plans, and specs in `concepts/`, `plans/`, and `specs/`, respectively, relative to the target repository root. Use these locations even when older artifacts live elsewhere.
- Generated files in these folders are temporary and gitignored. Never commit or force-add them.
- Keep artifacts available through implementation and final review. Leave cleanup to the human; do not delete them automatically.
- Permanent documentation must never link to, cite, or depend on these temporary files. Document lasting behavior and contracts directly in maintained documentation, grounded in the implementation.

## Validation

After edits, run applicable formatting and lint checks, then run only tests that directly cover this turn's changes. Skip tests if none are relevant. Leave full test groups to the Codex stop hook unless the user requests a broader run.

- For frontend changes, run `npm run format:changed` from **frontend/**. For backend changes, run `node .agents/validation/backend.mts --format` from the repository root. Respect exclusions, leave the Git index unchanged, coordinate before formatting unrelated user edits, and review the diff. Full-backend formatting requires an explicit request.
- For frontend or shared tooling changes, run `npm run lint` from **frontend/**. Treat warnings as failures. Use `lint:fix` deliberately and review its diff.
- From the repository root, run `node .agents/validation/test.mts --group NAME -- <runner arguments>` with a file or case filter. Use a pytest node ID for backend tests, Angular's `--include` for frontend tests, or `node --test <file>` for individual tooling tests. List groups with `node .agents/validation/test.mts --list`.
- For browser flow, frontend/backend integration, or local deployment changes, run the relevant [isolated E2E tests](docs/development/change-validation.md#end-to-end-browser-tests) with `node .agents/validation/test.mts --group e2e -- --grep '<pattern>'`.
- For contract changes, verify freshness using the [generated contract commands](docs/development/general.md#update-generated-contracts). See [local setup](docs/development/general.md#run-locally) for dependencies and use `npm.cmd` if PowerShell blocks `npm.ps1`.

Review and trust the Codex hooks before relying on them. The stop hook formats and lints applicable scopes, checks generated contract freshness, and runs the default non-E2E suite. Fix findings introduced by your work and get authorization for broader cleanup. Report incomplete validation and its cause.

## Communication Preferences

- Keep responses concise.
- Be critical; Be a collaborator; point out potential issues and missed details.
- Ask clarifying questions when necessary.
- Clearly communicate uncertainties; minimize false statements.

## Secrets

- Never commit API keys or tokens.
- Use `.env` files for local secrets.
