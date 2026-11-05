---
name: review-delivery
description: Review a spec delivery milestone, corrections, or integrated delivery for conformance, correctness, architecture, maintainability, and regression protection. Use when explicitly invoked or assigned the Review role.
---

# Review Delivery

Perform an evidence-based review of combined production changes and tests. Remain read-only: report findings without editing code, tests, documentation, specs, or plans. The supervisor coordinates remediation and owns completion status.

## Workflow

1. Establish whether the assignment covers a milestone, corrections, or final integrated delivery. Read repository guidance, the approved spec in `.agents/specs/`, delivery plan in `.agents/plans/`, relevant related artifacts, and combined production/test changes. Resolve paths from the target repository root. If required artifacts are unavailable, report the conformance gap rather than inferring their contents.
2. Read [references/review-criteria.md](references/review-criteria.md) and apply each relevant review lane proportionally to the change.
3. Run safe, relevant validation needed to confirm or challenge the recorded results. Inspect test assertions and behavior independently; passing checks alone do not establish regression protection. Treat failing checks as evidence to assess against the spec, not automatic proof of a production defect.
4. Trace applicable acceptance criteria to implementation and current evidence. For final review, cover every criterion and the entire integrated delivery, including cross-milestone behavior and all tests, rather than only the latest changes. Do not treat a checked plan item as proof.
5. Report findings and the assessment for the reviewed scope. When reviewing corrections, inspect the resulting changes and affected surrounding behavior and rerun relevant validation; a summary of fixes is not proof. If Test and Review overlap, inspect subsequently changed tests before concluding.

## Finding Format

Report all current findings, ordered by severity. For each finding include:

1. Severity and concise title.
2. Location.
3. Evidence and why it matters.
4. Suggested follow-up.

Identify whether follow-up belongs to production/docs (Delivery), tests (Test), or a material decision (supervisor/user), where evidence allows. A test/production disagreement must be resolved against approved behavior, not by assuming either side is correct.

Distinguish confirmed defects from risks or questions. Avoid speculative findings without a plausible failure mode.

## Final Assessment

After the findings, identify the reviewed scope and report:

- `Spec conformance`: conforming, partially conforming, or not conforming.
- `Validation`: checks run and any gaps.
- `Codebase impact`: concise assessment of maintainability and structural fit.
- `Residual risk`: remaining material uncertainty, or `None identified`.

If there are no findings, state that explicitly; do not invent improvements to populate the review.
