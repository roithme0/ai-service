---
name: prepare-spec
description: Create or refine an implementation-ready spec for a scoped software change and obtain approval. Use when explicitly invoked or assigned the Prepare role.
---

# Prepare Spec

## Establish the direction

Read repository guidance and inspect relevant code, docs, specs, and contracts. If the direction is still broad or spans multiple possible changes, use concept work first. Discuss the intended outcome, scope, UX, contracts, and integration impact. For frontend work, use the [frontend test guidance](../../../docs/development/frontend-testing.md#frontend-test-guidance) to identify outcomes the spec must make explicit.

Separate confirmed decisions, repository facts, and proposals. Resolve routine mechanics from established conventions. For material product, scope, UX, architecture, compatibility, or migration choices, obtain caller approval or explicit authority to decide. The caller is the user for direct invocation and the supervisor for delegated preparation. The supervisor can approve within the user's authorized scope and escalates choices beyond it. Record approvals and decisions made under delegated authority. Keep unresolved choices and recommendations with their tradeoffs under Open Questions.

## Draft and check readiness

Draft in the target repository's `specs/` directory using the [spec template](assets/spec-template.md). Follow local filenames or use `YYYY-MM-DD-<short-kebab-title>.md`. Link related concepts and specs relatively. Keep one spec for ordinary cross-layer work. Split coordination and implementation only when ownership, deployment, contract complexity, or sequencing warrants it. Keep implementation sequencing in the delivery plan. Remove resolved questions and empty optional sections.

Before handing off, check that:

- The outcome, scope, affected entry points, and behavior callers rely on are clear.
- Behavior describes starting states, inputs or actions, and observable results. Cover applicable invalid input, failure, retry, cancellation, and overlapping work, including effects on entered values, stored data, and pending state.
- Changed contracts state fields, meaning, and errors. Record material constraints and cite inherited constraints. For UI changes, state the intended experience and visual direction.
- Each material acceptance criterion has a stable ID, condition, and expected result that Delivery, Test, and Review can interpret independently.
- Material decisions have caller approval or were made under explicit authority. Summarize them before marking the spec ready and reuse approval for unchanged decisions. Discuss and record amendments before changing approved direction.

Hand off the spec path, acceptance criteria, approval evidence, and residual risks. A delegated Prepare assignment ends there. For direct preparation, proceed to delivery only when implementation of that scope is explicitly authorized, including through a request to deliver the spec.
