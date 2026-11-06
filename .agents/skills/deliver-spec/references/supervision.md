# Spec Delivery Supervision

The main agent owns coordination, user decisions, and overall completion. Delegate with the `prepare_spec`, `deliver_spec`, `test_delivery`, and `review_delivery` roles and their corresponding skills. Keep specialists focused on their role; the supervisor does not replace independent testing or review with its own implementation checks.

## Start

Read repository guidance and the named spec. An explicit request to deliver that spec, including `$deliver-spec`, authorizes implementation of that scope unless the user requested planning only; reuse existing authorization. If the direction is not ready, use Prepare Spec to resolve it with the user before delivery. Preserve the preparation skill's material decision and confirmation gates. Mark an authorized spec `approved` where supported.

Give Delivery the spec, authorization, repository context, and responsibility for a plan using [the delivery plan template](../assets/delivery-plan-template.md). Agree on a few substantial, testable milestones, with an architecture-sensitive slice early where applicable. Assign production/docs ownership to Delivery and independent coverage ownership to Test, including authority to improve Delivery-authored tests. Review remains read-only.

## Milestone Loop

1. Assign Delivery the milestone. It implements production code/docs, useful tests, and self-verification, then reports implementation progress.
2. Assign Test the milestone and evidence. It independently assesses coverage against the spec and risks, adds or corrects tests, and reports validation and gaps.
3. Assign Review the combined implementation and tests, relevant spec criteria, and evidence. It assesses conformance, correctness, architecture, maintainability, and regression protection.
4. Route material production/docs findings to Delivery and test findings to Test. A failing test is evidence, not a verdict about ownership: investigate intended behavior against the approved spec. Return material ambiguities or direction changes to the user through Prepare Spec; never silently change the contract to make checks pass.
5. Have Test validate relevant corrections and Review recheck them, including affected surrounding behavior. Close the milestone only when material findings are resolved and appropriate validation is complete. Record accepted residual risks explicitly; escalate any acceptance requiring a user decision.

Test and Review may overlap when useful, provided file ownership and the reviewed revision are clear. Review must inspect tests added after its earlier pass. Avoid concurrent edits to the same files; hand off ownership before either specialist changes tests. Keep progress moving without asking the user to approve routine internal milestones.

## Integrated Completion

After milestone closure, ask Test to assess integrated acceptance coverage, cross-milestone interactions, and relevant regressions, then complete missing protection and validation. Ask Review for an independent final assessment of the entire integrated delivery, including all production code/docs and tests, rather than only the latest delta. Route and recheck corrections through the same owners.

Only the supervisor marks the plan complete and spec `implemented`, after approved scope, integrated validation, final review, and material remediation are complete. Report outcomes, checks and results, deviations, and residual risks. Preserve explicit incomplete/blocked status when material work or evidence is missing; never infer completion from a checked plan or an implementation handoff.

For direct `$test-delivery` or `$review-delivery` requests, the main agent can perform that requested role using its skill without launching full delivery or changing overall completion status. For direct `$prepare-spec`, prepare the spec and stop at its handoff unless implementation was also authorized.
