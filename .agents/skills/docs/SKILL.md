---
name: docs
description: Write, update, or review maintained repository documentation, including READMEs, guides, and ADRs. Use for documentation changes, consolidation, or implementation changes that affect documented behavior. Excludes temporary plans, concepts, specs, and document artifact formatting.
---

# Docs

Maintain concise, repository-specific documentation grounded in the implementation.

## Workflow

1. Read applicable repository instructions and the relevant existing documentation. Follow established locations, structure, and terminology.
2. Inspect the implementation and relevant tests to establish current behavior. Identify affected documentation and the canonical home for each topic before adding pages.
3. Update affected documentation alongside implementation changes. For review-only requests, report unsupported claims and gaps without editing files.
4. Check changed links, command prerequisites and working directories, consistency with the implementation, and duplication. Use an existing documentation check when relevant; do not introduce tooling just to validate prose.

## Writing rules

- Prefer short sections, lists, tables, and small diagrams. Skip filler and empty sections.
- Explain repository-specific knowledge. Link to upstream documentation for general technology guidance.
- Give each topic one home; link to it instead of repeating it.
- Keep commands actionable: state the working directory and required prerequisites. Never include secrets.
- Describe current behavior; identify proposals explicitly.
- Preserve accepted ADR reasoning. Record changed decisions in a new ADR and link both records as superseded/superseding. Do not invent historical rationale.

## Keep out

- Exhaustive file lists, copied source code, and handwritten copies of generated API reference.
- Routine implementation choices, task logs, and PR summaries.
- Temporary plans, concepts, specs, and unfinished feature designs.
- One-time rollout, cutover, or migration hints that become obsolete after deployment. Keep these in release notes or task artifacts.
- Speculative pages for features or procedures we do not have.

Permanent documentation must not link to, cite, or depend on temporary artifacts. Store those artifacts according to the target repository's instructions.
