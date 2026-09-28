# Conversation API Contract Generation

## Status

Draft. The contract source, validation boundaries, and user-message wire shape are agreed. Generator selection and delivery details remain open. All four generic conversation success endpoints publish and validate typed response models. Error bodies are constructed from typed models and documented in OpenAPI. The current frontend transport remains in place.

## Context

The generic conversation HTTP API is implemented in `backend/app/sessions/http.py`. The published `@roithme0/chat-ui/conversation` entry point contains a handwritten transport, response interfaces, and five success-response parsers in `frontend/projects/chat-ui/conversation/src/conversation-api.ts`. The parsers validate session creation, messages, session snapshots, completed turns, and artifact envelopes at runtime. The controller relies on their validated output when reconciling failed requests.

Session creation, session reads, user-message appends, and completed turns declare Pydantic success response models and pass through FastAPI's response validation. Error responses use validated Pydantic models before direct `JSONResponse` serialization, and OpenAPI exposes their schemas. The frontend interfaces and backend response shapes can still change independently. Maintaining the parsers adds a second handwritten representation of the contract.

## Problem

The desired solution must reduce both contract drift and manual parsing work. TypeScript types alone do not validate JSON received at runtime. Removing the parsers in favor of generated types alone would weaken the transport boundary. Defining independent frontend validation schemas would simplify parsing but retain two separately maintained contract definitions.

The first slice resolved a shape mismatch: the backend previously omitted `turn_id` from user messages while the frontend parser supplied `turn_id: null`. The backend now sends explicit `null`, and the frontend parser requires it.

## Proposed Direction

Use typed Python response models as the authoritative contract for the generic conversation HTTP API. Ensure successful responses are validated against those models when produced, including any paths that continue to return `JSONResponse` directly. FastAPI's ordinary response-model path validates the returned value and serializes it to JSON; direct `JSONResponse` bypasses that path and must receive equivalent validation or be replaced. Publish accurate response schemas through FastAPI's OpenAPI document. OpenAPI contains the API schema; generate the frontend's TypeScript types and runtime validators from it. Use the validators at the HTTP transport boundary. Keep the transport's API error classification and the controller's recovery behavior.

The intent is one contract definition with two checks: backend validation before sending and frontend validation of received success responses. Generated output should replace the five handwritten success-response parsers and their duplicate interfaces. A repeatable generation command and a check for stale generated output should make drift visible before release. Check generated sources into this repository so building or publishing the independent chat UI package does not require a running backend.

Send `turn_id: null` for user messages and a string `turn_id` for assistant messages. The frontend should consume that wire shape directly rather than normalize omitted fields. This is an intentional backend/frontend contract change to deliver together.

Prefer generating only the types and validators initially. The current transport has meaningful error and reconciliation behavior; replacing it with a generated HTTP client is a separate decision with little direct benefit to the two stated problems. OpenAPI-to-Zod generation is a candidate, not a selected tool. The generated runtime dependency, output shape, version stability, and Angular package build need verification before choosing a generator.

## Contract Boundaries

- Model the shared session creation, snapshot, message, completed-turn, artifact-envelope, and error response shapes. Keep configuration-specific session `input` and artifact `payload` extensible at the generic conversation boundary. Domain validation remains with each configured agent and artifact handler.
- Preserve the distinction between a failed HTTP request, malformed or incomplete JSON, and a valid success response with the wrong shape. The controller currently uses these distinctions for reconciliation.
- Keep `@roithme0/chat-ui/ui` independent of HTTP and validation dependencies. Contract generation belongs to the optional `/conversation` entry point.
- Treat backend and frontend as one internal contract in this repository. When a wire shape changes, update both sides together rather than adding legacy parsing paths without a known external need. Published package consumers and deployment ordering still need consideration before a breaking release.

## Alternatives Considered

- **Keep handwritten parsers and add contract tests:** low tooling cost, but response definitions and parsing logic remain duplicated.
- **Handwrite frontend schemas with inferred TypeScript types:** reduces parser code and keeps runtime validation, but does not remove backend/frontend drift.
- **Generate TypeScript types from OpenAPI only:** removes duplicate interfaces but leaves handwritten runtime validation, or else removes the current validation guarantee.
- **Generate a full HTTP client:** can reduce transport code, but risks obscuring the existing error classification and recovery behavior. It is not required to solve contract drift or parsing overhead.
- **Generate validators from OpenAPI:** best matches both goals if the backend schema is accurate and the generated validators preserve the needed message unions and open artifact payloads. It introduces a generation workflow and a runtime dependency in the published package.

## Integration Impact

The backend must describe success and error responses accurately, including status codes and request shapes that are currently handled manually. Returning `JSONResponse` directly requires explicit care: documenting a response model does not by itself validate that direct response. The generated frontend contract must retain discriminated user and assistant messages and a completed-turn response whose message is assistant-authored.

The frontend package publishes `/conversation` separately but shares one package manifest with `/ui`. A runtime validator must be included in the published package's dependencies and tested through the library build. Generation should be deterministic and usable in local development and CI without fetching a live server. The checked-in OpenAPI and generated output should be checked against the current backend model, rather than becoming independent sources of truth.

## Delivery Progress

- **Completed first slice:** Session snapshot and user-message append success paths return Pydantic model instances and use FastAPI's validating response path. The session schema includes a discriminated user/assistant message union and an open artifact payload. Successful user messages send `turn_id: null`, and the frontend parser rejects omission.
- **Completed second slice:** Session creation and completed-turn success paths also return Pydantic model instances and publish response schemas. The completed-turn message is specifically assistant-authored. All four success paths use FastAPI's validating response path. Focused backend tests cover wire shapes, OpenAPI references, and invalid success bodies.
- **Completed error-contract slice:** Common error kinds and `invalid_input` issues use typed Pydantic models. Error helpers serialize only validated model instances to `JSONResponse`, preserving status codes and omitted `turn_id` fields. OpenAPI documents error schemas per endpoint. Direct `JSONResponse` still bypasses FastAPI response-model validation; the model construction is the error validation boundary.
- **Next slice:** Evaluate generator output against all success shapes, then replace handwritten frontend success parsers with generated validators while preserving error classification.

## Open Questions

- Which generator produces maintainable TypeScript types and runtime validators for this FastAPI OpenAPI output, and how does it handle unions, nullable values, dates, and arbitrary JSON payloads?
- Should generated frontend validators cover error bodies and configuration-specific requests in the initial generation workflow, or start with success bodies while preserving the current error classification?
- How should the generated-contract check run in the package and application release workflows without adding unnecessary build coupling?
- Do any consumers require a staged release for a revised message wire shape or a new package runtime dependency?

## Risks

- An incomplete OpenAPI document would automate the current drift rather than fix it. Backend response construction and schema output must be checked against real endpoint behavior.
- A generator may widen unions or mishandle open payloads, requiring a different tool or a narrow handwritten adapter.
- Generated validators add browser bundle weight and a dependency to the published library. The cost should be measured before adoption.
- Strict validation could reject additive server fields or existing responses unless the intended extension policy is explicit.

## Summary

Make the backend's typed conversation responses the contract source and derive both frontend types and runtime validators from OpenAPI. Send explicit `turn_id: null` for user messages. Retain the existing transport and recovery behavior. The success response models are in place; settle generator choice and generation checks before introducing generated frontend code.
