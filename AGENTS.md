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

## Temporary AI Artifacts

- Store implementation-specific concepts, plans, and specs in `.agents/concepts/`, `.agents/plans/`, and `.agents/specs/`, respectively, relative to the target repository root. Use these locations even when older artifacts live elsewhere.
- Generated files in these folders are temporary and gitignored. Never commit or force-add them. Keep the folder scaffolding and reusable skill resources tracked.
- Keep artifacts available through implementation and final review. Leave cleanup to the human; do not delete them automatically.
- Permanent documentation must never link to, cite, or depend on these temporary files. Document lasting behavior and contracts directly in maintained documentation, grounded in the implementation.

## Frontend Validation

- After frontend edits, run `npm run format:changed`, then `npm run lint`, `npm run test:tooling`, `npm run test:app`, and `npm run test:chat-ui` from `frontend`. On Windows, use `npm.cmd` if PowerShell blocks `npm.ps1`.
- Formatting covers whole staged, unstaged, and untracked frontend files without updating the Git index. Check the worktree first and coordinate before formatting files containing unrelated user edits. Generated conversation contracts, lockfiles, dependencies, caches, and build output are excluded.
- Lint covers the whole frontend, including the application, library, tests, handwritten scripts, and Angular templates. Both errors and warnings fail validation. Use `npm run lint:fix` only deliberately and review its diff; the hook and CI never apply ESLint fixes.
- Codex hooks snapshot frontend content before each prompt, then format changed files, lint, run tooling tests, and run both Angular test suites when content changes. Review formatting changes before completion. Successful checks are reused only for identical content after every check passes. Review and trust the hook definitions in Codex before relying on them.
- Address findings introduced by your work; broad existing-debt cleanup requires separate authorization. Report missing dependencies or failing checks as incomplete validation. Persistent hook failures request at most one continuation.

## Communication Preferences

- Keep responses concise.
- Be critical; Be a collaborator; point out potential issues and missed details.
- Ask clarifying questions when necessary.
- Clearly communicate uncertainties; minimize false statements.

## Secrets

- Never commit API keys or tokens.
- Use `.env` files for local secrets.
