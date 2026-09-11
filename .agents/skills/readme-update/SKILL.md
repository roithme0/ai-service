---
name: readme-update
description: Verify and update a repository `README.md` against the actual codebase and documentation. Use when the user asks to audit, refresh, or correct a README without inventing unsupported claims or adding new sections unless explicitly requested.
---

# README Update

Use this skill to keep an existing `README.md` accurate and grounded in the repo.

## Workflow

1. Read repo instructions first.
   - Check `AGENTS.md` and any repo-specific guidance before making changes.
   - Read the current `README.md` before inspecting the rest of the repo.

2. Preserve the document shape by default.
   - Do not invent new sections unless the user explicitly asks for them.
   - Prefer tightening or correcting existing text over rewriting the document.

3. Verify claims from source.
   - Check paths, scripts, configs, and active docs before updating README content.
   - Prefer `rg`, `find`, `sed`, `package.json`, `angular.json`, and the actual source tree over assumptions.
   - Treat commands, folder descriptions, tooling versions, localization details, and workflow references as claims that must be verified.
   - When available, spawning subagents is allowed for bounded parallel verification of independent repo areas or documentation sets.
   - Use subagents for evidence gathering, not for final README authorship. Give each subagent a narrow scope and integrate their findings yourself before editing.

4. Update only what the repo supports.
   - Remove or correct stale claims.
   - Add missing details only when they are clearly evidenced by the repo and fit inside an existing section.
   - Keep wording concrete and implementation-backed.

5. Verify after editing.
   - Run the repo-appropriate typecheck or other lightweight validation command when possible.
   - If validation is inconclusive or blocked, say so explicitly.

6. Report separately on notable mismatches.
   - Call out repo risks, dead code, or structural inconsistencies you discovered during the README audit when they matter, but do not fold speculative claims into the README itself.

## Output

- Summarize the README changes at a high level.
- Mention the verification command you ran and its result.
- Mention any important repo mismatches found during the audit that were not part of the README edit.
