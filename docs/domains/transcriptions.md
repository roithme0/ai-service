# Speech-to-text

`POST /api/v1/transcriptions` transcribes one raw audio recording without creating a conversation. Send the encoded bytes with their actual `Content-Type`, including any codec parameters. For example:

```sh
curl -X POST http://localhost:8004/api/v1/transcriptions \
  -H 'Content-Type: audio/webm;codecs=opus' \
  --data-binary @recording.webm
```

A successful response is `{"text":"..."}`. Text is returned as provided, including whitespace or an empty string. Language is detected automatically; there is no language hint or client model selector. The endpoint does not require a session or identity header.

Supported media types are `audio/webm`, `audio/mp4`, `audio/x-m4a`, `audio/m4a`, `audio/ogg`, `audio/wav`, `audio/x-wav`, `audio/wave`, `audio/mpeg`, `audio/mp3`, `audio/mpga`, `audio/flac`, and `audio/x-flac`. Type names are case-insensitive and codec parameters are accepted. The provider validates the encoded audio. The body must be nonempty and at most 25,000,000 bytes; there is no server-side duration limit. Five minutes of recording may exceed the byte limit depending on encoding.

Errors use `{"kind":"...","detail":"..."}` with safe fixed details:

| Status | Kind | Meaning |
| --- | --- | --- |
| 413 | `audio_too_large` | Audio exceeds the byte limit. |
| 415 | `unsupported_audio` | Content type is absent or unsupported. |
| 422 | `invalid_audio` | Audio is empty or identified as invalid by the provider. |
| 503 | `transcription_unavailable` | Configuration is unavailable or the provider is rate limited or unavailable. |
| 504 | `transcription_timeout` | The provider operation exceeded its deadline. |
| 502 | `transcription_failed` | Provider credentials, connection, response, or another upstream failure prevented transcription. |
| 500 | `internal_error` | An unexpected application error occurred. |

The backend sends audio directly to OpenAI's transcription API, with a 120-second total deadline and no automatic retries. It handles audio transiently in bounded per-request memory, does not save audio or transcripts, and cancels local work on detected disconnection. Provider processing and charges can continue after cancellation. Concurrent requests multiply memory use. OpenAI's [data controls](https://developers.openai.com/api/docs/guides/your-data#storage-requirements-and-retention-controls-per-endpoint) describe its current transcription endpoint retention and training policy; provider policy is not an application guarantee.

The gateway disables request buffering for this route, allows 60 seconds between incoming reads, and uses 150-second upstream send and read inactivity timeouts. Other proxies must permit the body size and accommodate these limits. See `/api/docs` for the complete contract.
