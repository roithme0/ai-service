# Recipe Improvement User-Message HTTP Boundary Delivery Plan

Date: 2026-09-12
Spec: docs/specs/2026-09-12-recipe-improvement-user-message-http-boundary.md

## Delivery Goal

Expose appending validated user text and reading ordered text messages through the existing recipe-improvement session HTTP boundary.

| Work item | Outcome | Key changes | Validation | Status |
| --- | --- | --- | --- | --- |
| 1 | User-message HTTP contract | Add strict request and message response adapters, mapping shared-store outcomes to the specified statuses | Transport tests | complete |
| 2 | Conversation read integration | Include the shared core's ordered messages in active session reads | Transport tests | complete |
| 3 | Integrated verification | Exercise affected and full backend tests; update delivery records | `pytest` | complete |

## Delivery Notes

- Invalid text is mapped from the shared core to `422`; FastAPI rejects malformed message request bodies, including extra fields, before any append.
- Final validation ran against the current tree with `docker run --rm -e PYTHONPATH=/app -v C:/Users/roithme0/Documents/Code/ai-service/backend:/app ai-service-test-backend-tests pytest -q`: 70 passed (two existing TestClient deprecation warnings).
