---
name: review-delivery
description: Review a spec delivery milestone, corrections, or integrated delivery for conformance, correctness, architecture, maintainability, and regression protection. Use when explicitly invoked or assigned the Review role.
---

# Review Delivery

Perform an evidence-based review of combined production changes and tests. Remain read-only: report findings without editing code, tests, documentation, specs, or plans. The supervisor coordinates remediation and owns completion status.

## Workflow

1. Establish the reviewed scope: milestone, corrections, or integrated delivery. Read repository guidance, the approved spec in `.agents/specs/`, delivery plan in `.agents/plans/`, and relevant production/test changes. Resolve paths from the target repository root and report missing artifacts.
2. Read [references/review-criteria.md](references/review-criteria.md) and apply each relevant review lane proportionally to the change.
3. Run safe, relevant validation needed to confirm or challenge the recorded results. Inspect test assertions and behavior independently; passing checks alone do not establish regression protection. Treat failing checks as evidence to assess against the spec, not automatic proof of a production defect.
4. Trace applicable acceptance criteria to implementation and current evidence. Final review covers every criterion, the integrated production changes and tests, and cross-milestone behavior. A checked plan item is not proof.
5. For corrections, inspect the fixes and affected surrounding behavior and run relevant validation. If Test and Review overlap, inspect subsequently changed tests before concluding. Report findings and the assessment for the reviewed scope.

## Finding Format

Report all current findings, ordered by severity. For each finding include:

1. Severity and concise title.
2. Location.
3. Evidence and why it matters.
4. Suggested follow-up.

Identify the remediation owner where evidence allows: Delivery for production/docs, Test for tests, or supervisor/user for material decisions.

Distinguish confirmed defects from risks or questions. Avoid speculative findings without a plausible failure mode.

## Final Assessment

After the findings, identify the reviewed scope and report:

- `Spec conformance`: conforming, partially conforming, or not conforming.
- `Validation`: checks run and any gaps.
- `Codebase impact`: concise assessment of maintainability and structural fit.
- `Residual risk`: remaining material uncertainty, or `None identified`.

If there are no findings, state that explicitly; do not invent improvements to populate the review.
