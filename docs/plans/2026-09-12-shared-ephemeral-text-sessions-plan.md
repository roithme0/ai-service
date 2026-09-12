# Shared Ephemeral Text Sessions Delivery Plan

Date: 2026-09-12
Spec: docs/specs/2026-09-12-shared-ephemeral-text-sessions.md

## Delivery Goal

Provide a domain-neutral, process-local typed session core with bounded ordered text messages, then migrate recipe improvement to its 90-minute lifecycle.

| Work item | Outcome | Key changes | Validation | Status |
| --- | --- | --- | --- | --- |
| 1 | Shared session contract | Add generic payload ownership, expiry lifecycle, explicit read and append outcomes, and message limits | Focused unit tests | complete |
| 2 | Recipe lifecycle migration | Delegate recipe session creation, lookup, and message appends to the shared core while retaining the 90-minute policy | Focused unit tests | complete |
| 3 | Integrated verification | Exercise the backend suite and update delivery records | `pytest` | complete |

## Delivery Notes

- The local shell has no `pytest`; validation ran in the repository's backend test container.
