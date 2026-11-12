# Image generation

After [configuring the capability](../operation.md#configuration), submit instructions to `POST /api/v1/image-generations` with an `Idempotency-Key` UUID and the `X-Application-User` identity assertion. Each generation produces one PNG. The assertion is unverified and must be protected by the hosting boundary.

Submission starts background work independently of the connection. Poll the returned status URL with the same identity, then use the completed result's content URL for repeated downloads. Reuse the same key and exact instructions to recover an uncertain submission without starting another generation. Each key is bound to its original instructions and owner. An explicit new attempt needs a new key.

Generation has no automatic retries. Provider processing and charges may continue after a timeout or shutdown. Cost is an optional estimate.

Generation references, idempotency keys, and image files are temporary and lost on restart. Consumers must download results they need to retain. Duplicate prevention lasts for the backend process lifetime.

See `/api/docs` for request, response, and error schemas, and the [implementation](../../backend/app/capabilities/image_generation/) for output settings and validation.

## Observation and controller

`GET /api/v1/image-generations/{id}/events` requires the same owner header as status. It sends full snapshot events immediately and on changes, then closes after a terminal snapshot. Observation is independent of generation execution.

The framework-independent `@roithme0/image-generation/controller` entrypoint supports submission, observation, and content downloads. Admission describes whether a submission was accepted, rejected, or remains uncertain. Recover uncertain admission with the original instructions and key. After losing observation of an accepted generation, reconnect or read status. Disposing the controller aborts local requests while backend generation continues.

Completed content is returned as a PNG Blob with a filename and snapshot. Consumers own any object URLs they create and must revoke them. Failed downloads can be retried while the completed snapshot remains available.

See the [controller](../../frontend/projects/image-generation/controller/src/controller.ts) and [HTTP transport](../../frontend/projects/image-generation/controller/src/transport.ts) for construction, methods, state transitions, and error handling.

## Reusable UI

`@roithme0/image-generation/ui` provides a standalone Angular component driven by host-supplied state and actions, with optional controller wiring. The host owns state publication and controller disposal. The UI owns its cached PNG Blob and object URLs. Content requests require the owner header.

The `instructionMode` input defaults to `editable` and is fixed for a component mount. In `hidden` mode, the host supplies instructions and explicitly starts generation through its controller or actions.

Retry after confirmed rejection or generation failure submits the attempt's exact instructions with a new key. Editable mode also allows revising instructions before explicit submission. Retry after a content-loading failure reloads the completed image.

Submission and recovery actions must publish accepted, rejected, or uncertain admission even when their callbacks reject. The UI relies on published state to classify admission.

The `actionError` output reports unexpected failures from submission, recovery, reconnection, and the primary action, including the operation and a user-facing message. Hosts decide how to present these errors. Expected admission and observation failures remain visible in the UI based on controller state. If submission or recovery fails without a decisive published state, the UI shows an unknown status rather than offering a potentially unsafe retry.

Refinement preserves the successful result and its submitted instructions alongside the editable draft until explicit submission. An optional async primary action receives the PNG Blob, filename, completed snapshot, and submitted instructions. The host owns persistence, closing, and navigation after handoff.

Give the component a bounded height for scrolling. See the [component and public types](../../frontend/projects/image-generation/ui/src/components/image-generation/image-generation.component.ts) and [host integration tests](../../frontend/projects/image-generation/ui/src/independent.spec.ts) for integration details.
