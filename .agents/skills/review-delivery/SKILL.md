---
name: review-delivery
description: Independently review a spec milestone, correction, or integrated delivery against approved behavior and codebase requirements. Use when explicitly invoked or assigned read-only Review.
---

# Review Delivery

Remain read-only. For delegated work, begin after Test's validation handoff. Read repository guidance, the approved spec and plan, production and test changes, and Test's evidence for the assigned scope. For a direct review, report missing evidence affecting the assessment.

- Independently trace each criterion to delivered behavior and appropriate verification evidence. For required test outcomes, check that assertions would fail on a plausible regression. Check material failure and recovery paths, contracts, UX, codebase fit, and operational risks. Consult the [risk prompts](references/review-criteria.md) for areas that warrant deeper review. For frontend changes, apply the [frontend test guidance](../../../docs/development/frontend-testing.md#frontend-test-guidance).
- Rerun relevant checks and investigate failures against the spec. For delegated corrections, wait for Test's revalidation, then review the fixes and affected surrounding behavior. Integrated review covers all criteria, combined production/docs and tests, and cross-milestone behavior.

Report all current findings in severity order. Give each a severity, title, location, evidence, consequence, and follow-up. Distinguish confirmed defects from risks and questions. Identify the owner when clear (Delivery for production/docs, Test for tests, supervisor or user for material decisions). State explicitly when there are no findings.

Close with the reviewed scope, spec conformance (conforming, partially conforming, or not conforming), validation results and gaps, codebase impact, and residual risk. The supervisor owns remediation coordination and completion.
