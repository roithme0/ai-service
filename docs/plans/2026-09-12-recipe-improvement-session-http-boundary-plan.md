# Recipe Improvement Session HTTP Boundary Delivery Plan

Date: 2026-09-12
Spec: docs/specs/2026-09-12-recipe-improvement-session-http-boundary.md

## Delivery Goal

Expose validated recipe-improvement session creation and active-session snapshot retrieval through the versioned FastAPI boundary using one serving-process store.

| Work item | Outcome | Key changes | Validation | Status |
| --- | --- | --- | --- | --- |
| 1 | Versioned session HTTP contract | Add request, success-response, and domain-error adapters over the existing input and lifecycle boundaries | Transport tests | complete |
| 2 | Process-local lifecycle integration | Bind both routes to one dependency-backed serving-process store and map active, unknown, and expired outcomes | Transport tests including injected expiry | complete |
| 3 | Integrated verification | Exercise the backend suite and update delivery records | `pytest` | complete |

## Delivery Notes

- The HTTP adapter converts finite JSON numeric or decimal-string ingredient amounts to `Decimal` before passing the request to the strict existing input boundary; it does not change domain validation rules.
- Validation ran using the existing backend test image with the current source mounted first on `PYTHONPATH`: 60 passed. The local environment does not have pytest installed.
