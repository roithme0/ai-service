---
name: test-delivery
description: Independently assess and improve tests for a spec delivery, milestone, or correction against agreed behavior and risks. Use for a delegated Test role or a request for spec-based coverage work.
---

# Test Delivery

Own independent coverage assessment and test changes. Delivery owns production code/docs; Review assesses both read-only. Work within the assigned scope and coordinate file ownership with the supervisor and Delivery before editing shared test files.

## Workflow

1. Read repository guidance, the approved spec, and established contracts. Derive expected behavior, relevant cases, and material risks before inspecting the new implementation or Delivery's tests. For a standalone request, establish the requested scope and report missing artifacts rather than inventing requirements.
2. Inspect the delivery plan, implementation, tests, and reported validation. Map applicable acceptance criteria and risks to current evidence, including relevant failure paths, boundaries, state transitions, and cross-layer contracts. Assess coverage independently of Delivery's conclusions.
3. Add, extend, or correct tests where they provide meaningful regression protection, including tests written by Delivery. Choose the smallest useful scope. Use a real browser for layout or native browser behavior; do not create new end-to-end tests without an explicit user request. Maintain or repair existing end-to-end coverage where appropriate. Explain any removal of tests under repository rules.
4. Run relevant validation and investigate failures against approved behavior. A failure may indicate a test defect, production defect, or spec ambiguity. Report production defects through the supervisor and escalate material ambiguities; do not change expectations merely to match implementation.
5. Recheck assigned corrections and their affected coverage. At integrated handoff, trace all acceptance criteria to current evidence, check cross-milestone interactions, and identify untested risks or unavailable checks.

## Handoff

Report coverage assessed, tests changed and why, checks and results, uncovered criteria, defects, and residual uncertainty. Give enough evidence for Review to inspect assertions and production behavior independently. Do not mark milestones closed or the spec implemented; the supervisor owns overall status.

When invoked directly, perform the requested testing work and report production findings to the user. Do not expand into production changes or a full delivery workflow without authorization.
