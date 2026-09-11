# Delivery Review Criteria

Apply the lanes relevant to the delivered change and scale depth with risk.

## Spec Conformance

- Every acceptance criterion has implementation and validation evidence.
- Delivered behavior matches the outcome, scope, decisions, UI direction, contracts, and constraints.
- No material behavior or scope was added without an updated decision record.

## Functional and Contract Correctness

- Important success, empty, loading, failure, and recovery paths behave as intended.
- API, event, data, storage, and integration boundaries remain internally consistent.
- Compatibility, migration, rollout, and error semantics are correct where applicable.

## User Experience

- UI behavior follows the specified experience and established design system.
- Important states, responsive behavior, accessibility, feedback, and recovery are covered proportionally.
- Implementation details do not undermine the intended information hierarchy or interaction model.

## Regression Protection

- Tests protect meaningful behavior, branching logic, state transitions, and contract boundaries.
- Relevant automated checks pass, and untested areas are identified.
- Validation evidence is current and appropriate to the affected layers.

## Codebase Fit

- No dead code, unnecessary complexity, duplication, or stale compatibility remains.
- Responsibilities and dependencies sit in appropriate modules.
- Naming, typing, error handling, and structure match established conventions.
- The change does not introduce avoidable architectural or folder-structure drift.

## Operational Risk

- Security, privacy, performance, observability, deployment, and rollback implications are addressed where material.
- Residual risks and deferred work are visible rather than silently accepted.
