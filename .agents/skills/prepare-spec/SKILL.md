---
name: prepare-spec
description: Pressure-test a scoped software change and create or refine a lightweight, implementation-ready spec. Use only when explicitly invoked for spec-driven delivery; use concept work instead when the direction is still broad or spans multiple potential changes.
---

# Prepare Spec

Turn an intended software change into an approved direction without prescribing implementation details that the codebase already answers.

## Workflow

1. Read the repository guidance and inspect the relevant code, documentation, existing specs, and established contracts.
2. Confirm that the request is a bounded change. If it is primarily an exploratory product or architecture direction spanning multiple potential changes, explain that it belongs in concept work before creating a spec.
3. Spar with the user for as many rounds as the change needs. Pressure-test goals, scope, behavior, UX, contracts, constraints, alternatives, and integration impact. Follow the repository's clarification batch limit; do not force a fixed number of rounds.
4. Once the core direction is stable, create or update a spec from [assets/spec-template.md](assets/spec-template.md). Treat it as the current decision record, not a conversation transcript.
5. Keep only decisions the implementation cannot safely recover from the codebase. Scale detail with ambiguity, blast radius, irreversibility, and contract or migration risk.
6. Review the draft against the codebase and related specs. Surface conflicts or missing decisions and continue sparring until it satisfies the readiness criteria.
7. Present the resulting spec and unresolved non-blocking risks. Do not begin implementation. An explicit request to run `$deliver-spec` is the implementation approval gate.

## Readiness Criteria

A spec is ready for delivery when:

- The outcome and meaningful scope boundaries are clear.
- Product, behavioral, and contract decisions that affect correctness are settled.
- Acceptance criteria describe observable, verifiable outcomes.
- No open question would require the implementer to invent a product, architecture, compatibility, or migration decision.
- For UI-affecting work, the intended experience, interaction model, important states, and visual direction are clear enough that implementation does not require inventing product decisions.
- For non-UI work, the absence of UI impact is explicit.

## Detail and Splitting

- Omit obvious implementation mechanics, exhaustive file lists, and details already established by the codebase.
- Include error cases, compatibility, migration, security, rollout, or validation detail only in proportion to their risk.
- Use one spec by default, including for ordinary cross-layer work.
- Split coordination and implementation specs only when independent ownership, deployment boundaries, contract complexity, or sequencing makes the separation useful.
- Keep implementation sequencing out of the spec; it belongs to `$deliver-spec`.

## Spec Maintenance

- Store specs in the repository's established spec location and follow its naming conventions. If none exist, use `docs/specs/YYYY-MM-DD-<short-kebab-title>.md`.
- Link a related concept when the spec realizes part of a broader accepted direction.
- Remove resolved questions and empty optional sections instead of preserving placeholders.
- Do not silently change an approved decision. Return to sparring and make the change visible.
