---
name: test-delivery
description: Independently assess and improve regression coverage for an approved spec, milestone, or correction. Use for a delegated Test assignment or direct spec-based testing request.
---

# Test Delivery

Own coverage assessment, test changes, and formal test execution. Coordinate shared test files with Delivery and the supervisor.

## Derive cases from the spec

For new scope or amended criteria, start with the approved spec, assigned scope, and repository guidance. Use the [frontend test guidance](../../../docs/development/frontend-testing.md#frontend-test-guidance) for frontend work. Use the spec or an explicitly identified pre-delivery baseline for contract details. Defer the plan, current implementation and tests, diffs, and change summaries.

Record each case's criterion ID, starting condition, input or action, and observable expected result, including relevant failures, boundaries, and risks. Escalate ambiguities in expected behavior. Hand off the case record and wait for the supervisor to release implementation evidence. For a direct request, report missing artifacts and record cases before inspecting available implementation evidence. Reuse case records for unchanged criteria.

## Assess and validate

With implementation evidence available, inspect the plan, affected public entry points, and existing assertions. Account for verification of each criterion and map required test outcomes to assertions that would fail on regression. Fill meaningful gaps and improve Delivery-authored tests as warranted under repository test and E2E rules. Run relevant checks and investigate failures against approved behavior. Report production defects and spec ambiguities to the supervisor or direct caller.

Revalidate corrections and affected surrounding behavior. For integrated delivery, assess all criteria, cross-milestone interactions, and relevant regressions. Hand off criteria with verification evidence, including applicable assertions, test changes and rationale, checks and results, gaps, defects, and remaining uncertainty. A standalone request authorizes testing within its scope. Production changes or full delivery require separate authorization.
