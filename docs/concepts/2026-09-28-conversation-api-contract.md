# Conversation API Contract Generation

## Status

Draft. The contract source, validation boundaries, user-message wire shape, and generation dependencies are agreed. All four generic conversation success endpoints publish and validate typed response models. Error bodies are constructed from typed models and documented in OpenAPI. Hey API now generates checked-in TypeScript types, and the frontend transport uses them while retaining handwritten runtime parsers. Zod validation remains the next slice.

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

Generate only types and validators initially with `@hey-api/openapi-ts` as a pinned frontend development dependency and regular `zod` as a runtime dependency of the published chat UI package. Use Hey API's TypeScript and Zod plugins without generating an HTTP client. The current transport has meaningful error and reconciliation behavior; replacing it is a separate decision with little direct benefit to the two stated problems. Export the document from FastAPI's `app.openapi()` for reproducible generation without a running server; `/api/v1/openapi.json` remains useful for live inspection. The generator output, version stability, and Angular package build still need verification during implementation.

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
- **`typed-openapi` with Zod:** a temporary schema-only trial preserved the key response shapes, but its generated strict objects reject additive fields. It remains a viable fallback rather than the selected generator.
- **Hey API with Zod Mini:** a temporary trial generated matching TypeScript response types and validators for the current OpenAPI document. Zod Mini reduced the isolated trial bundle size, but bundle size is secondary to contract fidelity and maintainability. Regular Zod is the selected runtime; a separate regular-Zod trial was intentionally skipped.
- **Valibot runtime:** the temporary generated validator accepted an array artifact payload although the backend contract requires an object, so that output would need correction before use.

## Integration Impact

The backend must describe success and error responses accurately, including status codes and request shapes that are currently handled manually. Returning `JSONResponse` directly requires explicit care: documenting a response model does not by itself validate that direct response. The generated frontend contract must retain discriminated user and assistant messages and a completed-turn response whose message is assistant-authored.

The frontend package publishes `/conversation` separately but shares one package manifest with `/ui`. Zod must be included in the published package's dependencies and tested through the library build. Hey API should be pinned as a development dependency because its generator interface can change. Generation should be deterministic and usable in local development and CI without fetching a live server. The checked-in OpenAPI and generated output should be checked against the current backend model, rather than becoming independent sources of truth.

## Delivery Progress

- **Completed first slice:** Session snapshot and user-message append success paths return Pydantic model instances and use FastAPI's validating response path. The session schema includes a discriminated user/assistant message union and an open artifact payload. Successful user messages send `turn_id: null`, and the frontend parser rejects omission.
- **Completed second slice:** Session creation and completed-turn success paths also return Pydantic model instances and publish response schemas. The completed-turn message is specifically assistant-authored. All four success paths use FastAPI's validating response path. Focused backend tests cover wire shapes, OpenAPI references, and invalid success bodies.
- **Completed error-contract slice:** Common error kinds and `invalid_input` issues use typed Pydantic models. Error helpers serialize only validated model instances to `JSONResponse`, preserving status codes and omitted `turn_id` fields. OpenAPI documents error schemas per endpoint. Direct `JSONResponse` still bypasses FastAPI response-model validation; the model construction is the error validation boundary.
- **Completed snapshot alignment:** The frontend snapshot type and parser now require and return the backend's `expires_at` field.
- **Completed generator evaluation:** A temporary Hey API and Zod Mini trial preserved the required `turn_id: null`, nullable fields, assistant-only completed-turn message, and object artifact payload. The generated response types matched the validators' inferred types in a strict TypeScript check. The user selected Hey API with regular Zod without further runtime evaluation.
- **Completed Hey API types slice:** Pinned `@hey-api/openapi-ts` generates checked-in OpenAPI and TypeScript types from `app.openapi()`. The conversation entry point exports the generated response names directly; `ApiMessage` remains a derived union because the generator does not name the message union. A generation command and drift check are available; the package release workflow runs the check. Existing parsers continue to validate runtime responses and now enforce the generated contract's assistant-only completed turn, object artifact payload, and terminal turn kind.
- **Next slice:** Add regular Zod and generated validators, then replace handwritten frontend success parsers while preserving error classification. Validate the generated output and Angular package build as part of implementation.

## Open Questions

- Should generated frontend validators cover error bodies and configuration-specific requests in the initial generation workflow, or start with success bodies while preserving the current error classification?
- Should the application image release workflow also run the contract drift check, in addition to the package release workflow?
- Do any consumers require a staged release for a revised message wire shape or a new package runtime dependency?

## Risks

- An incomplete OpenAPI document would automate the current drift rather than fix it. Backend response construction and schema output must be checked against real endpoint behavior.
- Regular-Zod output from Hey API still needs contract tests against the actual generated code; the completed runtime trial used Zod Mini.
- Generated validators add browser bundle weight and a dependency to the published library. Bundle size is secondary, but the Angular package build should still be checked.
- The trial Hey API schemas accepted and stripped additive object fields. The implementation should confirm that regular-Zod output retains this behavior and that it fits the intended extension policy.

## Summary

Make the backend's typed conversation responses the contract source and derive both frontend types and regular-Zod runtime validators with Hey API. Send explicit `turn_id: null` for user messages. Retain the existing transport and recovery behavior. Generated types and the drift check are in place; replacing the handwritten parsers with generated Zod validators is the next implementation work.
