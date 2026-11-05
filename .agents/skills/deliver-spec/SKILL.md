---
name: deliver-spec
description: Coordinate approved spec delivery through implementation, independent testing, and review; perform implementation when delegated the Delivery role. Use only when explicitly invoked with the spec to deliver.
---

# Deliver Spec

Convert an approved direction into a verified implementation. The main agent supervises; delegated Delivery agents implement.

## Routing

- When invoked directly by the user in the main agent, follow [references/supervision.md](references/supervision.md). Coordinate the roles rather than taking the Delivery role yourself.
- When assigned the Delivery role by a supervisor, follow the implementation workflow below for the assigned milestone or corrections. Return progress to the supervisor; do not spawn another delivery workflow or declare overall completion.
- If delegation is unavailable, report that limitation before substituting a combined-role workflow; do not claim independent testing or review occurred.

## Before Delivery

1. Read the repository guidance, target spec, related concepts or specs, and relevant code.
2. Use the supervisor's supplied implementation authorization for the named spec and scope. Return missing authorization or material decisions to the supervisor; do not infer them from a task assignment alone.
3. Confirm that no open question or codebase conflict requires a product, architecture, contract, compatibility, or migration decision. If one does, pause affected work and return the smallest useful decision to the supervisor.
4. Create an outcome-oriented plan from [assets/delivery-plan-template.md](assets/delivery-plan-template.md) in `.agents/plans/` relative to the target repository root. Follow existing filename conventions there; otherwise use `YYYY-MM-DD-<short-kebab-title>-plan.md`. Link the spec using a relative Markdown link.

## Delivery

- Plan a few substantial milestones that each yield a testable, reviewable outcome. Put architecture-sensitive behavior in an early useful slice. Use the template for milestone and final validation tracking.
- Implement the assigned milestone, add useful development and regression tests, and self-verify before handoff. Delivery does not own complete coverage: Test independently assesses and may revise these tests.
- Keep implementation progress and evidence current. Return each meaningful milestone for Test and Review before advancing past the supervisor's milestone closure; these are agent coordination steps, not requests for user approval.
- Inspect and adapt to the codebase as implementation proceeds. The plan is a coordination aid, not a prohibition on ordinary implementation judgment.
- Make decisions that preserve the approved outcome and established codebase conventions. Record noteworthy deviations, risks, and follow-up opportunities briefly in the plan.
- Validate changes proportionally and support integrated checks across milestones. Treat failing tests as evidence to investigate against the approved spec, not automatic proof that production code or the test is wrong. Escalate material ambiguities.
- Handle production or documentation findings assigned by the supervisor. Coordinate test file edits with Test; do not overwrite another agent's work.
- Report implementation progress only. The supervisor owns milestone closure and the spec's final `implemented` status after testing, review, and remediation.
- Update maintained documentation for lasting behavior and contract changes. Never link to, cite, or create dependencies on temporary artifacts in permanent documentation.

## Pause Conditions

Pause affected work and return the decision to the supervisor (or the user when operating directly) when new information:

- Changes user-visible behavior or the approved scope.
- Requires a material architecture, contract, compatibility, data migration, or rollout decision.
- Reveals a conflict or ambiguity that prevents a correct implementation.
- Requires destructive, externally mutating, or otherwise newly authorized action.
- Blocks meaningful progress after safe in-scope alternatives have been exhausted.

Do not pause for routine implementation details, straightforward test failures, renamed or relocated code, or small plan adjustments that preserve the approved outcome. Resolve those, validate the result, and mention noteworthy deviations at handoff.

## Scope Changes

If delivery requires a material scope or direction change, stop implementation at a coherent point. Explain the evidence, affected spec decisions, and recommended amendment. Resume only after the direction is agreed and the spec and plan reflect it.

## Handoff

Return the milestone or correction scope, changed areas, implementation status, checks and results, deviations, and residual risks. Identify evidence and areas needing independent coverage. Do not describe an implementation handoff as overall delivery completion.
