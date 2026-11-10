# Image generation

After [configuring the capability](../operation.md#configuration), submit instructions to `POST /api/v1/image-generations` with an `Idempotency-Key` UUID and the `X-Application-User` identity assertion. Each generation produces one PNG. The assertion is unverified and must be protected by the hosting boundary.

Submission starts background work independently of the connection. Poll the returned status URL with the same identity, then use the completed result's content URL for repeated downloads. Reuse the same key and exact instructions to recover an uncertain submission without starting another generation. A key cannot be reused with different instructions; an explicit new attempt needs a new key. Keys are scoped to the owner, and other owners cannot inspect the generation.

Generation has no automatic retries. Provider processing and charges may continue after a timeout or shutdown. Cost is an optional estimate, not a billing record.

Generation references, idempotency keys, and image files are temporary and lost on restart. Consumers must download results they need to retain; duplicate prevention does not extend across restarts.

See `/api/docs` for request, response, and error schemas, and the [implementation](../../backend/app/capabilities/image_generation/) for output settings and validation.

## Observation and controller

`GET /api/v1/image-generations/{id}/events` requires the same owner header as status. It sends full snapshot events immediately and on changes, then closes after a terminal snapshot. Reconnect or read status after a lost stream; observation never starts or cancels generation.

The framework-independent `@roithme0/image-generation/controller` entrypoint provides explicit submission and recovery of uncertain admission using the original instructions and key. A lost observation is distinct from a failed generation: reconnect or read status without resubmitting. Disposing the controller aborts local requests; it does not cancel generation.

Completed content is returned as a PNG Blob with a filename and snapshot. The host owns any object URLs it creates and must revoke them. Failed downloads can be retried while the completed snapshot remains available.

See the [controller](../../frontend/projects/image-generation/controller/src/controller.ts) and [HTTP transport](../../frontend/projects/image-generation/controller/src/transport.ts) for construction, methods, state transitions, and error handling.

## Reusable UI

`@roithme0/image-generation/ui` provides a standalone Angular component driven by host-supplied state and actions. It can use the supplied controller through explicit host wiring or work independently. The host owns state publication and controller disposal; the UI owns its cached PNG Blob and object URLs. Content must be loaded with the owner header, never through a bare backend URL.

Submission and recovery actions must publish accepted, rejected, or uncertain admission even when their callbacks reject; callback settlement alone cannot classify admission. Recovery repeats the original uncertain request, while reconnection observes the known generation without resubmitting.

Refinement keeps the successful result and its submitted instructions separate from the editable draft. Returning to the result preserves draft edits; an explicit new generation replaces the result. An optional async primary action receives the PNG Blob, filename, completed snapshot and submitted instructions. Competing actions are disabled while it runs; failure permits retry, and success leaves closing or navigation to the host. Save or import the Blob during handoff when it must survive backend restart.

Give the component a bounded height for scrolling. See the [component and public types](../../frontend/projects/image-generation/ui/src/components/image-generation/image-generation.component.ts), [styling variables](../../frontend/projects/image-generation/ui/src/components/image-generation/image-generation.component.scss), and [independent-host and controller-wiring tests](../../frontend/projects/image-generation/ui/src/independent.spec.ts) for integration details.
