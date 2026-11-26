---
name: deliver-spec
description: Coordinate delivery of a named spec through implementation, independent testing, and review, or implement as the delegated Delivery role. Use on an explicit delivery request or supervisor assignment.
---

# Deliver Spec

A direct delivery request uses the [supervisor workflow](references/supervision.md). Follow the instructions below only for a delegated Delivery assignment.

## Implement the assigned scope

- Read repository guidance, the spec, relevant related artifacts, and code. Confirm the supervisor supplied implementation authorization for the named scope.
- Use the [delivery plan template](assets/delivery-plan-template.md) to create or update the shared plan in the target repository's `plans/` directory. Follow local filenames or use `YYYY-MM-DD-<short-kebab-title>-plan.md`. Link the spec relatively. Plan substantial, testable milestones and surface architecture-sensitive behavior in an early useful slice. Keep implementation status current and reuse the plan for corrections.
- Own production code and maintained docs for lasting behavior and contract changes. Keep permanent docs independent of temporary spec, concept, and plan artifacts. Development tests and checks are available for self-verification. Follow the [frontend test guidance](../../../docs/development/frontend-testing.md#frontend-test-guidance) when writing frontend tests and coordinate shared test files with Test, which owns coverage and formal validation.
- Resolve routine implementation choices and adapt the plan within the approved outcome. Record material deviations and risks. Pause affected work if authorization is missing, progress remains blocked after safe alternatives, or a conflict requires a material scope, behavior, architecture, contract, compatibility, migration, or rollout decision. Give the supervisor the evidence, affected decisions, and recommended amendment. Resume after agreement and any required spec and plan updates.

Report implementation completion, changed areas, deviations, and remaining risks or decisions for the assigned milestone or correction. Identify any outstanding work when blocked. Wait for supervisor closure before advancing to the next milestone.
