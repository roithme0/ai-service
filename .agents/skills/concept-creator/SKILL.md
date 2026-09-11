---
name: concept-creator
description: Develop and maintain product or architecture concepts through interactive discussion and iterative markdown updates. Use when Codex should pressure-test an idea, compare alternatives, surface conflicts, evaluate integration into the current workspace or nested repos, and create or keep updating a concept document, typically under `docs/concepts/` or the repo's equivalent concept folder.
---

# Concept Creator

Develop the concept in chat first, then keep the written concept synchronized with the latest agreed direction.

## Workflow

1. Load local repo guidance first.
   - Read `AGENTS.md`, `README.md`, and any directly relevant workflow docs before non-trivial work.
   - Honor local collaboration rules, clarification limits, and edit gates.

2. Discover the local concept conventions before drafting.
   - Prefer the folder named by the user.
   - Otherwise inspect the repo for the concept-doc location, usually `docs/concepts/` or a close equivalent.
   - Sample a few existing concept docs to infer filename shape, title style, section patterns, tone, and expected level of detail.
   - Preserve the local house style when it is clear.

3. Spar with the user before locking the concept.
   - Pressure-test the idea for goals, alternatives, conflicts, ownership boundaries, rollout seams, and likely integration points.
   - Use the whole workspace as context, including nested repos, when checking feasibility or impact.
   - Ask concise clarifying questions in small batches when required.
   - State uncertainties and weak assumptions explicitly.

4. Start the document as soon as the seed direction is clear.
   - Do not wait for every detail to be settled.
   - Create an initial concept doc once there is enough direction to record the current position and open questions.
   - Write the document as a current-state concept, not as a transcript of the conversation.

5. Keep the concept doc current throughout the discussion.
   - Update the same concept file after substantive decisions, scope changes, or resolved conflicts.
   - Remove stale contradictions instead of layering new text on top of obsolete text.
   - Keep unresolved questions explicit when the discussion has not closed them yet.

6. Keep concept and spec boundaries clean.
   - Capture rationale, problem framing, scope boundaries, ownership, integration implications, and recommended direction.
   - Do not turn the concept into an implementation plan unless the repo's concept style clearly expects that.
   - Include concrete implementation implications only when they clarify the concept decision.

## Document Shaping

Infer the structure from the local concept corpus instead of forcing one universal template.

When the repo has no clear concept pattern, use this minimal fallback structure:

- `# <Concept Title>`
- `## Status`
- `## Context` or `## Goal`
- `## Problem`
- `## Proposed Direction` or `## Decision`
- `## Scope Boundaries`
- `## Integration Impact`
- `## Open Questions`
- `## Risks`
- `## Summary`

Prefer short sections with decisive wording. Keep prose dense and concrete.

## Naming

- Reuse the local naming convention when one exists.
- If the repo commonly prefixes concept docs with a date, follow that convention.
- If there is no visible convention, use a clear kebab-case concept filename and place it in the repo's concept-doc folder.

## Guardrails

- Do not assume the current workspace's folder layout is universal; rediscover it in each repo.
- Do not hard-wire service names or repository names into the skill instructions.
- Do not invent consensus. Mark tentative conclusions as tentative.
- Do not hide important tradeoffs; surface them in chat and reflect the chosen direction in the doc.
- Do not create a fresh concept file for every minor refinement when one evolving concept file is the better fit.

## Output

- Summarize the conceptual movement since the last revision, not just that the file changed.
- Mention the concept file path you created or updated.
- Call out remaining risks, open questions, or assumptions that still need user confirmation.