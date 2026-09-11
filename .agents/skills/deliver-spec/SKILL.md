---
name: deliver-spec
description: Plan and autonomously implement an approved software spec, pausing only when a material exception prevents safe delivery. Use only when explicitly invoked with the spec to deliver.
---

# Deliver Spec

Convert an approved direction into a verified implementation without stopping at routine internal checkpoints.

## Before Delivery

1. Read the repository guidance, target spec, related concepts or specs, and relevant code.
2. Treat an explicit request to run `$deliver-spec` as approval to implement the named draft unless the user asks for planning only. Mark the spec `approved` when its format supports status.
3. Confirm that no open question or codebase conflict requires a product, architecture, contract, compatibility, or migration decision. If one does, pause and present the smallest useful decision to the user.
4. Create an outcome-oriented plan from [assets/delivery-plan-template.md](assets/delivery-plan-template.md) in the repository's established plan location. If none exists, use `docs/plans/YYYY-MM-DD-<short-kebab-title>-plan.md`.

## Delivery

- Execute all plan items continuously and keep their status current.
- Organize work into coherent outcomes or workstreams, not human review checkpoints.
- Inspect and adapt to the codebase as implementation proceeds. The plan is a coordination aid, not a prohibition on ordinary implementation judgment.
- Make decisions that preserve the approved outcome and established codebase conventions. Record noteworthy deviations, risks, and follow-up opportunities briefly in the plan.
- Validate each workstream proportionally and run the relevant integrated checks before handoff.
- Mark the spec `implemented` after the approved scope is implemented and validation is complete. Do not mark it implemented when material work remains.

## Pause Conditions

Pause and involve the user when new information:

- Changes user-visible behavior or the approved scope.
- Requires a material architecture, contract, compatibility, data migration, or rollout decision.
- Reveals a conflict or ambiguity that prevents a correct implementation.
- Requires destructive, externally mutating, or otherwise newly authorized action.
- Blocks meaningful progress after safe in-scope alternatives have been exhausted.

Do not pause for routine implementation details, straightforward test failures, renamed or relocated code, or small plan adjustments that preserve the approved outcome. Resolve those, validate the result, and mention noteworthy deviations at handoff.

## Scope Changes

If delivery requires a material scope or direction change, stop implementation at a coherent point. Explain the evidence, affected spec decisions, and recommended amendment. Resume only after the direction is agreed and the spec and plan reflect it.

## Handoff

Summarize the implemented outcomes, validation performed, deviations, and residual risks. Recommend `$review-delivery` for the independent final conformance and codebase review.
