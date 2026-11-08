# Image generation

After [configuring the capability](../operation.md#configuration), submit instructions to `POST /api/v1/image-generations` with an `Idempotency-Key` UUID and the `X-Application-User` identity assertion. Each generation produces one PNG. The assertion is unverified and must be protected by the hosting boundary.

Submission starts background work independently of the connection. Poll the returned status URL with the same identity, then use the completed result's content URL for repeated downloads. Reuse the same key and exact instructions to recover an uncertain submission without starting another generation. A key cannot be reused with different instructions; an explicit new attempt needs a new key. Keys are scoped to the owner, and other owners cannot inspect the generation.

Generation has no automatic retries. Provider processing and charges may continue after a timeout or shutdown. Cost is an optional estimate, not a billing record.

Generation references, idempotency keys, and image files are temporary and lost on restart. Consumers must download results they need to retain; duplicate prevention does not extend across restarts.

See `/api/docs` for request, response, and error schemas, and the [implementation](../../backend/app/capabilities/image_generation/) for output settings and validation.
