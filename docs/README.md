# AI Service documentation

These docs contain only the essential guidance for getting started with the repository. The code is the main documentation and should explain its behavior through clear structure and readable implementation. Keep written guidance concise and avoid duplicating details already expressed in code to reduce documentation drift.

## What belongs where

| Location | Purpose | Include |
| --- | --- | --- |
| [../README.md](../README.md) | What the product offers | A concise product introduction, screenshot, feature highlights, and a link to this index. Keep technical detail in the documentation below. |
| [README.md](README.md) | How to use and maintain the documentation | Documentation scope, page responsibilities, writing rules, and exclusions. |
| [decisions/](decisions/) | Why we chose an approach | A shared [ADR template](decisions/template.md) and one numbered record per significant architectural decision: context, decision, alternatives, consequences, status, and acceptance date. |
| [domains/](domains/) | What our language means | Contracts and terminology for [conversations](domains/conversations.md), [artifacts](domains/artifacts.md), and [embeddings](domains/embeddings.md). |
| [navigation.md](navigation.md) | How the current system fits together | Responsibilities, boundaries, code entry points, and representative flows. Link to relevant code and tests. |
| [development.md](development.md) | How to work on the code | Local setup, running, testing, debugging, contract generation, and AI-assisted development workflows, skills, and hooks. |
| [operation.md](operation.md) | How to run deployed environments | Deployment, configuration, updates, persistence, backup/recovery, and troubleshooting. Document available procedures and their limitations. |
| [assets/screenshots/](assets/screenshots/) | Where documentation images live | Screenshots referenced by documentation and the root README. |

## Writing rules

- Prefer short sections, lists, tables, and small diagrams. Skip filler and empty sections.
- Explain repository-specific knowledge. Link to upstream documentation for general technology guidance.
- Give each topic one home; link to it instead of repeating it.
- Keep commands actionable: state the working directory and required prerequisites. Never include secrets.
- Update affected documentation with the implementation. Describe current behavior; identify proposals explicitly.
- Preserve accepted ADR reasoning. Record changed decisions in a new ADR and link both records as superseded/superseding. Do not invent historical rationale.

## Keep out

- Exhaustive file lists, copied source code, and handwritten copies of generated API reference.
- Routine implementation choices, task logs, and PR summaries.
- Temporary plans, concepts, specs, and unfinished feature designs.
- One-time rollout, cutover, or migration hints that become obsolete after deployment. Keep these in release notes or task artifacts.
- Speculative pages for features or procedures we do not have.
