---
name: review-delivery
description: Review a completed spec delivery for conformance, validation gaps, regressions, and broader codebase quality. When supervising delegated delivery, drive ordinary findings to resolution with the implementing agent. Use only when explicitly invoked for the final delivery review.
---

# Review Delivery

Perform an evidence-based final review of a completed spec delivery. Keep the initial review independent from implementation, then resolve findings through the implementing agent when acting as its supervisor.

## Workflow

1. Read the repository guidance, delivered spec, delivery plan, related artifacts, and implementation diff or touched code.
2. Read [references/review-criteria.md](references/review-criteria.md) and apply each relevant review lane proportionally to the change.
3. Run safe, relevant validation needed to confirm or challenge the recorded delivery results.
4. Trace every acceptance criterion to implementation and evidence. Do not treat a checked plan item as proof.
5. Establish the findings before beginning remediation so implementation ownership does not weaken the review.
6. Select the applicable completion mode below.

## Completion Modes

### Supervised Resolution

Use this mode when you delegated the delivery and the implementing agent remains available.

- Send confirmed findings back to that agent, individually or in coherent groups. Include the location, evidence, expected outcome, and required validation.
- Have the implementing agent correct all findings that stay within the approved spec and do not meet a user-escalation condition.
- Inspect the resulting changes and validation evidence yourself. Do not accept the agent's summary as proof.
- Repeat review and remediation until the completion or stopping conditions below are met.
- Do not ask the user to mediate routine implementation findings.

### Review Only

Use this mode when there is no delegated implementing agent available. Report findings without editing code, specs, or plans unless the user explicitly requests fixes.

## Completion and Stopping Conditions

- Complete the supervised review when no material findings remain and the relevant validation passes.
- Involve the user when remediation would change the approved scope or approved user-visible behavior; requires a material architecture, contract, compatibility, migration, or rollout decision; encounters blocking ambiguity; or requires new authorization.
- Stop the remediation loop and surface the evidence when the same material finding remains after two focused correction attempts, or when remediation causes recurring regressions or scope churn.
- Defer a non-material finding only for a concrete reason. Do not prolong remediation for speculative or cosmetic improvements that are not findings under the review criteria.

## Finding Format

Report only unresolved findings after supervised resolution; in review-only mode, report all findings. Order findings by severity. For each finding include:

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

For supervised resolution, also summarize material corrections made during review. If there are no unresolved findings, state that explicitly; do not invent improvements to populate the review.
