# Supervise Spec Delivery

## Start

Read repository guidance and the named spec. An explicit request to deliver it, including `$deliver-spec`, authorizes implementation of that scope unless the user requested planning only. Reuse existing authorization. If the spec is unready, use Prepare Spec and respect its caller approval rules. Assign implementation only after readiness and authorization are established. Mark the spec `approved` where supported.

Delegate with `deliver_spec`, `test_delivery`, and `review_delivery`, using `prepare_spec` when preparation is needed. If delegation is unavailable, report the limitation before combining roles and describe the resulting limits on independence. Give Delivery the spec, authorization, and repository context. Agree on milestones in the shared plan. Coordinate file ownership before overlapping edits. The supervisor handles user decisions and milestone closure without seeking approval for routine internal steps.

## Close each milestone

1. Assign Delivery the milestone. Wait for implementation completion before starting Test, including case derivation.
2. Start a fresh Test agent without inherited conversation history. Supply the approved spec and assigned scope. Keep the plan, changes, and Delivery's handoff out of this first assignment. After Test returns spec-derived cases, resume that agent with implementation evidence for coverage assessment, test changes, and formal validation.
3. Wait for Test's coverage and validation handoff. Assign Review the approved spec, plan, combined changes, and Test's evidence.
4. Route production and docs findings to Delivery and test findings to Test. Determine ownership against the approved spec when a failing test leaves the cause unclear. Use Prepare Spec for material ambiguities or direction changes, escalating decisions beyond existing authorization to the user.
5. Reuse cases for unchanged criteria. For amended criteria or new scope, repeat the implementation-complete and fresh Test gates for that part. Have Test revalidate corrections and affected surrounding behavior before Review rechecks. Close the milestone once material findings are resolved and appropriate validation is complete. Record residual risks and escalate any acceptance requiring a user decision.

## Close the delivery

After milestone closure, have Test assess integrated coverage, interactions, and regressions using existing case records and fill any remaining gaps. Route newly approved integrated scope through the milestone loop. After Test's integrated handoff, have Review independently assess the entire delivery and recheck corrections after Test revalidates them.

Only the supervisor marks the plan complete and the spec `implemented`, once the approved scope, integrated validation, final review, and material remediation are complete. Keep incomplete or blocked status when material work or evidence is missing. Report outcomes, checks and results, deviations, and residual risks.
