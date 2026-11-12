---
name: concept-creator
description: Develop temporary product or architecture concepts in `concepts/` through interactive discussion and iterative markdown updates. Use to pressure-test an idea, compare alternatives, surface conflicts, and evaluate integration into the current workspace or nested repos.
---

# Concept Creator

Pressure-test an idea with the user and maintain one evolving document that reflects the current direction.

## Workflow

1. Resolve the target repository root, including in workspaces with nested repositories. Read applicable instructions and relevant code and documentation; inspect related repositories when integration depends on them.
2. Discuss goals, alternatives, tradeoffs, scope, ownership, and integration impact. Ask about choices that materially affect the direction and distinguish evidence, assumptions, proposals, and agreed decisions.
3. Create a draft once the initial direction is clear, subject to local edit gates. Store it in `concepts/` relative to the target repository root. Follow existing naming conventions; otherwise use `<short-kebab-title>.md`.
4. Update the same document as decisions evolve. Replace stale conclusions, resolve contradictions, and retain unanswered questions. Record the current concept rather than the discussion transcript.
5. Keep implementation detail only where it explains feasibility, a tradeoff, or an integration boundary. A concept does not authorize implementation or replace an implementation-ready spec.

## Document Shaping

Follow the local concept style when useful. Otherwise include the problem and goal, proposed direction and alternatives, scope, integration impact, and material risks or open questions. Add status when it helps distinguish tentative and agreed direction. Omit empty sections and a summary that merely repeats the document.

## Output

Report the document path, material changes in direction, and remaining decisions or risks.
