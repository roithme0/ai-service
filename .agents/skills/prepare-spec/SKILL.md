---
name: prepare-spec
description: Pressure-test a scoped software change and create or refine a lightweight, implementation-ready spec. Use only when explicitly invoked for spec-driven delivery; use concept work instead when the direction is still broad or spans multiple potential changes.
---

# Prepare Spec

Turn an intended software change into an approved direction without prescribing implementation details that the codebase already answers.

## Workflow

1. Read the repository guidance and inspect the relevant code, documentation, existing specs, and established contracts.
2. Establish a bounded change. If the request still spans multiple possible directions, use concept work before creating a delivery spec.
3. Discuss goals, scope, behavior, UX, contracts, constraints, alternatives, and integration impact. Ask about unresolved material choices and recommend options with tradeoffs. Follow local clarification rules; use as many rounds as needed.
4. Create or update a draft spec from [assets/spec-template.md](assets/spec-template.md) as the direction takes shape. Treat it as the current decision record, not a conversation transcript. Keep unconfirmed material choices under Open Questions, including any recommendations.
5. Review the draft against the codebase, related specs, and readiness criteria. Resolve conflicts and missing decisions; scale detail with ambiguity and risk.
6. Summarize material decisions and obtain caller approval before marking the spec ready. The caller is the user for direct invocation or the orchestrating agent for delegated preparation. Reuse prior approval for unchanged decisions. Hand off the spec path, acceptance criteria, approval evidence, and residual risks.

Stop at the handoff unless implementation of the agreed scope is already explicitly authorized. A request to deliver the spec, including `$deliver-spec`, provides that authorization.

## Decisions and Assumptions

- Distinguish confirmed decisions, repository facts, and proposals. Cite evidence for inherited constraints; current behavior does not establish the intended change.
- Material product, scope, UX, architecture, compatibility, and migration choices require caller approval or explicit authorization to decide. An orchestrating agent may approve within the user's authorized scope; escalate choices beyond that authority to the user. Record decisions made within that authority. Recommendations and unanswered questions remain proposals.
- Resolve routine implementation mechanics from established conventions without further confirmation.

## Readiness Criteria

A spec is ready for delivery when:

- The outcome and meaningful scope boundaries are clear.
- Material decisions meet the confirmation rules above and are recorded.
- Acceptance criteria describe observable, verifiable outcomes.
- No open question would require the implementer to invent a product, architecture, compatibility, or migration decision.
- UI-affecting work specifies the intended experience, interactions, important states, and visual direction.
- For non-UI work, note that there is no UI impact.

## Detail and Splitting

- Keep decisions the implementer cannot safely recover from the codebase. Omit routine mechanics and exhaustive file lists.
- Include error cases, compatibility, migration, security, rollout, or validation detail only in proportion to their risk.
- Use one spec by default, including for ordinary cross-layer work.
- Split coordination and implementation specs only when independent ownership, deployment boundaries, contract complexity, or sequencing makes the separation useful.
- Keep implementation sequencing out of the spec; it belongs to `$deliver-spec`.

## Spec Maintenance

- Store specs in `specs/` relative to the target repository root. Follow existing filename conventions there; otherwise use `YYYY-MM-DD-<short-kebab-title>.md`.
- Use relative Markdown links to related concepts and specs, including across artifact folders.
- Remove resolved questions and empty optional sections instead of preserving placeholders.
- Do not silently change an approved decision. Discuss and record the amendment.
