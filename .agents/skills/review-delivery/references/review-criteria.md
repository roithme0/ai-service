# Review Risk Prompts

Consult the relevant prompts when a change touches these areas.

- **State and recovery** — Check empty and loading states, invalid inputs, retries and interrupted or overlapping operations. Check effects on persisted data and pending work.
- **Contracts and rollout** — Trace API, event, data, and storage boundaries. Check error semantics, compatibility, migration, cutover, and rollback where applicable.
- **User experience** — Check responsive behavior, accessibility, feedback, information hierarchy, and fit with the specified experience and existing design system.
- **Regression evidence** — Check that fixtures and mocks preserve the behavior claimed by the test. Look for gaps in important state transitions and contract boundaries across test layers.
- **Codebase fit** — Look for dead code, duplication, stale compatibility, misplaced responsibilities, or avoidable architectural drift. Check that permanent docs stand on their own.
- **Operations** — Assess material security, privacy, performance, observability, deployment, and rollback implications.
