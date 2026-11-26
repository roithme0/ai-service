# Agentic Coding

| Resource | Purpose |
| --- | --- |
| [AGENTS.md](../../AGENTS.md) | Coding rules, approval boundaries, and required validation. |
| [Skills](../../.agents/skills/) | Reusable workflows, including concept, spec, delivery, review, and Pydantic AI guidance. Read the relevant `SKILL.md` before use. |
| [Validation](../../.agents/validation/) | Shared checks used by manual commands, CI, and agent hooks. |
| [Hooks](../../.codex/hooks.json) | Codex adapter snapshots content before prompts and validates affected scopes on stop. |
| [Project configuration](../../.codex/config.toml) | Angular CLI and OpenAI documentation MCP connections. |

Review and trust hooks before relying on them. Relevant hooks perform [validation](change-validation.md), including contract freshness checks; unchanged discussion turns run none. Their commands invoke Node.js using absolute checkout paths; run validation manually if unavailable. Hook state and reports are gitignored under `.codex-validation/`.

For approved milestones, `deliver-spec` coordinates Delivery, followed by independent Test with `test-delivery`, then Review with `review-delivery`. Test derives cases from the approved spec before receiving implementation evidence.

Temporary concepts, plans, and specs belong in repository-root `concepts/`, `plans/`, and `specs/`, respectively, outside commits and permanent documentation. Invoke spec and delivery workflows explicitly; routine changes do not require them.
