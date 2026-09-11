# Agents Guide

## Mandatory Context Docs

- Before non-trivial work, read `README.md`.

## Coding Rules

- No destructive commands.
- Avoid wide refactors without explicit confirmation.
- Strict typing is required. Avoid `Any` and untyped parameters/returns.
- Keep code comments to a minimum; avoid commenting the obvious.

## AI Workflow

- Ask before large refactors.
- If a user message is phrased as a question, answer it in chat first and ask for explicit confirmation before making code or file changes.
- Confirm before touching build or tooling config.
- Summarize changes and call out risks.
- Treat backend API as an internal contract for this repo's frontend by default: ship backend/frontend contract changes together, and do not preserve legacy compatibility unless explicitly required for a feature or an external consumer.
- Write tests where they provide meaningful regression protection: critical user flows, branching logic, stateful behavior, contract boundaries, and bug-prone edge cases. Avoid low-signal tests that only restate implementation details. Do not remove existing tests unless they are redundant, obsolete, flaky, or block legitimate refactoring, and explain the reason when removing them.

## Communication Preferences

- Keep responses concise.
- Be critical; Be a collaborator; point out potential issues and missed details.
- Ask clarifying questions when necessary.
- Clearly communicate uncertainties; minimize false statements.

## Secrets

- Never commit API keys or tokens.
- Use `.env` files for local secrets.
