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
- Write tests where they provide meaningful regression protection: critical user flows, branching logic, stateful behavior, contract boundaries, and bug-prone edge cases. Avoid low-signal tests that only restate implementation details. Do not remove existing tests unless they are redundant, obsolete, flaky, or block legitimate refactoring, and explain the reason when removing them.
- Create new end-to-end tests only as an explicitly requested, intentional step. Adjust and repair existing end-to-end tests as needed during routine changes, preserving their regression coverage.

## Temporary AI Artifacts

- Store implementation-specific concepts, plans, and specs in `.agents/concepts/`, `.agents/plans/`, and `.agents/specs/`, respectively, relative to the target repository root. Use these locations even when older artifacts live elsewhere.
- Generated files in these folders are temporary and gitignored. Never commit or force-add them. Keep the folder scaffolding and reusable skill resources tracked.
- Keep artifacts available through implementation and final review. Leave cleanup to the human; do not delete them automatically.
- Permanent documentation must never link to, cite, or depend on these temporary files. Document lasting behavior and contracts directly in maintained documentation, grounded in the implementation.

## Validation

After edits, run the applicable commands in order:

| Scope | Working directory | Commands |
| --- | --- | --- |
| Frontend | `frontend` | `npm run format:changed`, `npm run lint`, `npm run test:tooling`, `npm run test:app`, `npm run test:chat-ui`, `npx playwright test` |
| Backend | Repository root | `node .agents/validation/backend.mts --format`, `node --test .agents/validation/shared.test.mts .agents/validation/backend.test.mts` |
| Backend | `backend` | `.venv/Scripts/python.exe -m pytest` (`.venv/bin/python` on Unix) |

Use `npm.cmd` if PowerShell blocks `npm.ps1`. See [development setup and contract validation](docs/development.md) for dependencies, editor configuration, and generated API contracts.

- Format only changed staged, unstaged, and untracked files, respecting configured exclusions and leaving the Git index unchanged. Coordinate before formatting unrelated user edits and review the resulting diff. Full-backend formatting requires an explicit request.
- Lint errors and warnings fail validation. Run `lint:fix` only deliberately and review its diff; hooks and CI never apply lint fixes.
- Hooks update the local Docker stack using Docker's build cache, then run Playwright for frontend, backend, or local deployment changes. Manual equivalent: `node .agents/validation/e2e.mts`. Docker and Playwright Chromium must be available; report missing prerequisites as incomplete validation.
- Review and trust hooks before relying on them. They validate changed scopes automatically and reuse success only for identical content after all checks pass. Shared hook changes validate both scopes; persistent failures request at most one continuation.
- Fix findings introduced by your work; broader cleanup requires authorization. Report missing dependencies or failed checks as incomplete validation. Hooks never install dependencies automatically.

## Communication Preferences

- Keep responses concise.
- Be critical; Be a collaborator; point out potential issues and missed details.
- Ask clarifying questions when necessary.
- Clearly communicate uncertainties; minimize false statements.

## Secrets

- Never commit API keys or tokens.
- Use `.env` files for local secrets.
