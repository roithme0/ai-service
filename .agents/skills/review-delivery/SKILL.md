---
name: review-delivery
description: Review a completed spec delivery for conformance, validation gaps, regressions, and broader codebase quality. Use only when explicitly invoked for the final delivery review.
---

# Review Delivery

Perform an evidence-based final review of a completed spec delivery. Report findings without editing code, specs, or plans.

## Workflow

1. Read the repository guidance, delivered spec in `.agents/specs/`, delivery plan in `.agents/plans/`, related artifacts in `.agents/concepts/` or the other artifact folders, and implementation diff or touched code. Resolve paths from the target repository root. If required artifacts are unavailable, report the conformance gap rather than inferring their contents.
2. Read [references/review-criteria.md](references/review-criteria.md) and apply each relevant review lane proportionally to the change.
3. Run safe, relevant validation needed to confirm or challenge the recorded delivery results.
4. Trace every acceptance criterion to implementation and evidence. Do not treat a checked plan item as proof.
5. Report findings and the final assessment. When reviewing corrections, inspect the resulting changes and rerun relevant validation; a summary of fixes is not proof.

## Finding Format

Report all current findings, ordered by severity. For each finding include:

1. Severity and concise title.
2. Location.
3. Evidence and why it matters.
4. Suggested follow-up.

Distinguish confirmed defects from risks or questions. Avoid speculative findings without a plausible failure mode.

## Final Assessment

After the findings, report:

- `Spec conformance`: conforming, partially conforming, or not conforming.
- `Validation`: checks run and any gaps.
- `Codebase impact`: concise assessment of maintainability and structural fit.
- `Residual risk`: remaining material uncertainty, or `None identified`.

If there are no findings, state that explicitly; do not invent improvements to populate the review.
