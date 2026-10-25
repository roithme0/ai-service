# Embeddings

After [configuring the provider](../operation.md#embedding-capability), send `POST /api/v1/embeddings` with:

```json
{"profile": "semantic-text-v1", "input": "Tomato soup"}
```

An embedding profile fixes vector compatibility. Use the same profile for stored content and search queries. Changing the embedding space requires a new profile and migration of stored vectors.

See `/api/docs` for request, response, and error schemas, and the [implementation](../../backend/app/embeddings/) for behavior.
