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
- Create new end-to-end tests only when explicitly requested. Maintain and repair existing end-to-end tests as needed, preserving their regression coverage.
- Remove existing tests only when redundant, obsolete, flaky, or blocking legitimate refactoring; explain the reason.

## Temporary AI Artifacts

- Store implementation-specific concepts, plans, and specs in `.agents/concepts/`, `.agents/plans/`, and `.agents/specs/`, respectively, relative to the target repository root. Use these locations even when older artifacts live elsewhere.
- Generated files in these folders are temporary and gitignored. Never commit or force-add them.
- Keep artifacts available through implementation and final review. Leave cleanup to the human; do not delete them automatically.
- Permanent documentation must never link to, cite, or depend on these temporary files. Document lasting behavior and contracts directly in maintained documentation, grounded in the implementation.

## Validation

After frontend, backend, or shared tooling edits, run from the **repository root**:

```powershell
node .agents/validation/run.mts
```

This formats changed files, lints, and runs all non-E2E tests. Install frontend dependencies, Playwright Chromium, and the backend local venv with `test` and `dev` extras first; see [development setup](docs/development.md).

For focused tests during implementation, discover groups with `node .agents/validation/test.mts --list` and select them with `--group NAME`. Focused runs do not replace full validation. `--scope frontend|backend` limits formatting and lint only; tests remain the full non-E2E suite.

For browser flow, frontend/backend integration, or local deployment changes, also run `node .agents/validation/e2e.mts` from the repository root. It updates Docker and runs Playwright.

- Format only changed staged, unstaged, and untracked files, respecting configured exclusions and leaving the Git index unchanged. Coordinate before formatting unrelated user edits and review the resulting diff. Full-backend formatting requires an explicit request.
- Lint errors and warnings fail validation. Run `lint:fix` only deliberately and review its diff; hooks and CI never apply lint fixes.
- Review and trust hooks before relying on them. Hooks format and lint relevant scopes and run all non-E2E tests. They reuse success only for identical inputs after all checks pass and request at most one continuation for persistent failures.
- Fix findings introduced by your work; broader cleanup requires authorization. Report missing dependencies or failed checks as incomplete validation. Hooks never install dependencies automatically.

## Communication Preferences

- Keep responses concise.
- Be critical; Be a collaborator; point out potential issues and missed details.
- Ask clarifying questions when necessary.
- Clearly communicate uncertainties; minimize false statements.

## Secrets

- Never commit API keys or tokens.
- Use `.env` files for local secrets.
