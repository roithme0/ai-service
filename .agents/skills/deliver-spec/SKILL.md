---
name: deliver-spec
description: Coordinate approved spec delivery through implementation, independent testing, and review, or implement an assigned milestone as the delegated Delivery role. Use on an explicit request to deliver a named spec or a supervisor's Delivery assignment.
---

# Deliver Spec

Convert an approved direction into a verified implementation. The main agent supervises; delegated Delivery agents implement.

## Routing

- When invoked directly by the user in the main agent, follow [references/supervision.md](references/supervision.md). Coordinate the roles rather than taking the Delivery role yourself.
- When assigned the Delivery role by a supervisor, follow the implementation workflow below for the assigned milestone or corrections. Return progress to the supervisor; do not spawn another delivery workflow or declare overall completion.
- If delegation is unavailable, report that limitation before substituting a combined-role workflow; do not claim independent testing or review occurred.

## Before Delivery

1. Read the repository guidance, target spec, related concepts or specs, and relevant code.
2. Use the supervisor's supplied implementation authorization for the named spec and scope. Return missing authorization to the supervisor.
3. Confirm that no open question or codebase conflict requires a product, architecture, contract, compatibility, or migration decision. If one does, pause affected work and return the smallest useful decision to the supervisor.
4. Create or update the shared delivery plan using [assets/delivery-plan-template.md](assets/delivery-plan-template.md) in `plans/` relative to the target repository root. Reuse it for later milestones and corrections. Follow local filenames; otherwise use `YYYY-MM-DD-<short-kebab-title>-plan.md`. Link the spec with a relative Markdown link.

## Delivery

- Plan substantial milestones that each yield a testable, reviewable outcome. Put architecture-sensitive behavior in an early useful slice and track milestone and integrated evidence in the plan.
- Implement the assigned milestone, add useful development and regression tests, and self-verify before handoff. Delivery does not own complete coverage: Test independently assesses and may revise these tests.
- Keep progress and evidence current. Hand off each milestone for Test and Review and wait for supervisor closure before advancing. These are internal coordination steps, not user approval gates.
- Adapt the plan to repository evidence while preserving the approved outcome and established conventions. Record noteworthy deviations and risks briefly.
- Validate changes proportionally and support integrated checks across milestones. Treat failing tests as evidence to investigate against the approved spec, not automatic proof that production code or the test is wrong. Escalate material ambiguities.
- Handle production or documentation findings assigned by the supervisor. Coordinate shared test file ownership with Test before editing.
- Update maintained documentation for lasting behavior and contract changes. Never link to, cite, or create dependencies on temporary artifacts in permanent documentation.

## Pause Conditions

Pause affected work and return the decision to the supervisor (or the user when operating directly) when new information:

- Changes approved user-visible behavior or scope.
- Requires a material architecture, contract, compatibility, data migration, or rollout decision.
- Reveals a conflict or ambiguity that prevents a correct implementation.
- Requires an action outside existing authorization or prohibited by repository rules.
- Blocks meaningful progress after safe in-scope alternatives have been exhausted.

Do not pause for routine implementation details, straightforward test failures, renamed or relocated code, or small plan adjustments that preserve the approved outcome. Resolve those, validate the result, and mention noteworthy deviations at handoff.

For a material direction change, explain the evidence, affected spec decisions, and recommended amendment. Resume affected work after agreement and updates to the spec and plan.

## Handoff

Return scope, changed areas, implementation status, checks and results, deviations, residual risks, and areas needing independent coverage. The supervisor owns milestone closure and the spec's final `implemented` status; an implementation handoff is not overall completion.
