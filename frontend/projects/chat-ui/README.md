# Chat UI

`@roithme0/chat-ui` provides an Angular 22 conversation UI with optional AI Service integration. It has no Kochwiki dependency.

| Entry point                       | API                                                                                                                         |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `@roithme0/chat-ui/ui`            | `ChatUiComponent`, content/status types, artifact renderers, and capabilities. Renders host state without backend requests. |
| `@roithme0/chat-ui/conversation`  | `SessionController`, `HttpSessionTransport`, snapshot mapping, and generated session types.                                 |
| `@roithme0/chat-ui/transcription` | `HttpTranscriber` and typed backend transcription errors.                                                                   |
| `@roithme0/chat-ui/recording`     | `BrowserAudioRecorder` and typed recording outcomes. Framework-independent microphone capture without transcription or UI.  |

The root entry point exports no API. All entry points share one version.

## Browser audio recording

Import `BrowserAudioRecorder` from `@roithme0/chat-ui/recording` for microphone capture without Angular, conversation, or backend dependencies. It provides no recording UI or transcription. Importing and constructing a recorder are safe outside a browser; `start()` requires HTTPS or localhost, `getUserMedia`, `MediaRecorder`, and microphone permission.

`start()` resolves when recording finishes, with `kind: 'recorded'`, `'cancelled'`, or `'failed'`. Successful results contain `recording.blob`, `mimeType`, `durationMs`, and `stopReason`; failures contain a typed `error`. A second start while busy fails without disturbing the active recording. See the [recording types](https://github.com/roithme0/ai-service/blob/production/frontend/projects/chat-ui/recording/src/recording-types.ts) for outcomes and states.

- Use the `state` getter or optional constructor callback to reflect recording progress and block conflicting submissions while requesting access, recording, or finalizing.
- Call `stop()` to finalize audio. During a pending permission request, it cancels instead. Call `cancel()` to discard audio, including pending finalization, and reuse the recorder. Cancellation settles immediately; any stream granted afterward is released.
- Cancel on conversation changes and call `dispose()` when the owning component is destroyed. Disposal cancels pending work and permanently prevents recording.

Recording stops automatically after five minutes of capture, excluding the permission wait, with `stopReason: 'duration-limit'`; manual stop reports `'manual'`. Browser throttling or suspension can delay the limit. `durationMs` measures elapsed capture time through the stop request, rather than encoded-media duration.

The browser chooses the encoding; consumers must check whether their transcription service accepts the returned MIME type. Capture interruption discards partial audio. Hosts own error presentation, page-backgrounding policy, and storage or object URLs for returned audio; the recorder does not persist it.

## Composer dictation

Opt in through the `dictation` and `dictationContextKey` inputs on `ai-chat-ui`. See the [configuration types](ui/src/dictation.ts) and [live demo](../../src/app/pages/live-demo/live-demo.component.ts) for default recorder, transcription adapter, and host toast wiring. Backend limits and errors belong to the [speech-to-text contract](../../../docs/domains/transcriptions.md).

- Keep the configuration reference stable. Its factory must return an independent recorder; the composer owns cancellation and disposal.
- Supply a non-null context key independent of the backend session ID. Keep it stable during a conversation. Before switching or resetting, propagate a new key to the composer synchronously; the live demo shows this ordering.
- Provide accessible toast presentation with safe messages through `onError`; there is no library default. Custom transcribers use the exported [TranscriptionError](transcription/src/http-transcriber.ts) for operational failures. Intentional cancellation is silent.

The microphone is hidden without configuration or browser recording support. Transcripts append to the editable draft for review and are never sent automatically. Hiding the page cancels capture but allows transcription already in progress to finish. Context/configuration changes, destruction, and editing disable cancel pending work and discard late results. Audio is not stored by the library.

## Host setup

Configure the scope in the consumer's `.npmrc` and authenticate with package read access:

```ini
@roithme0:registry=https://npm.pkg.github.com
```

Then install:

```sh
npm install @roithme0/chat-ui
```

Provide compatible Angular 22, Material, and CDK dependencies and a global Material theme:

```css
@import '@angular/material/prebuilt-themes/magenta-violet.css';
```

Give the host a bounded height; the component fills it and scrolls history internally. Typography is inherited. Icons are bundled in the `ai-chat` namespace; no icon font or host registration is needed. See the packaged `MATERIAL_ICONS_LICENSE` for attribution and Apache 2.0 terms.

### Assets

Add to the application's build `assets` array in `angular.json`:

```json
{
  "glob": "**/*",
  "input": "node_modules/@roithme0/chat-ui/public",
  "output": "assets/chat-ui"
}
```

Set `mascotAssetPath="assets/chat-ui/images"`; the default is `images`, relative to the application base URL. The package supplies `mascot-idle.png` and `maskot-working.png` (spelling intentional). Any `active` turn selects the working mascot, even after final text arrives.

## AI Service integration

A standalone host using the scripted `visual-demo` configuration:

```typescript
import { Component, OnInit, OnDestroy, signal } from '@angular/core';
import {
  ChatUiComponent,
  JSON_ARTIFACT_CAPABILITY,
  type ChatSubmission,
} from '@roithme0/chat-ui/ui';
import {
  SessionController,
  HttpSessionTransport,
  type SessionViewState,
} from '@roithme0/chat-ui/conversation';

@Component({
  selector: 'app-chat',
  imports: [ChatUiComponent],
  template: `<ai-chat-ui
    bannerTitle="Visual Demo"
    bannerDescription="Any text advances the scripted sequence."
    mascotAssetPath="assets/chat-ui/images"
    [turns]="chat().turns"
    [composerDisabled]="chat().composerDisabled"
    [composerEditingDisabled]="chat().composerEditingDisabled"
    [conversationStatus]="chat().status"
    (messageSubmitted)="submit($event)"
    (statusActionTriggered)="act($event)"
  />`,
})
export class ChatHost implements OnInit, OnDestroy {
  readonly chat = signal<SessionViewState>({
    snapshot: null,
    admission: 'idle',
    observation: 'connecting',
    turns: [],
    composerDisabled: true,
    composerEditingDisabled: false,
    status: null,
  });
  private readonly controller = new SessionController(
    new HttpSessionTransport('/api/v1', 'visual-demo', 'demo:default'),
    (state) => this.chat.set(state),
  );

  ngOnInit(): void {
    void this.controller.start({ artifact_capabilities: [JSON_ARTIFACT_CAPABILITY] });
  }
  ngOnDestroy(): void {
    this.controller.dispose();
  }
  submit(value: ChatSubmission): void {
    void this.controller.submit(value.text, value.acknowledge);
  }
  act(id: string): void {
    void this.controller.performAction(id);
  }
}
```

- The transport takes the URL prefix before `/agents`, configuration key, and identity string `${encodeURIComponent(issuer)}:${encodeURIComponent(subject)}` sent as `X-Application-User` on every request. Both components must be nonempty. This assertion does not authenticate the caller; see the [session rules](https://github.com/roithme0/ai-service/blob/production/docs/domains/conversations.md#session-rules).
- `start(initialization?)` accepts `initial_context` and `artifact_capabilities`; replacement sessions reuse them. Server validation is authoritative.
- Bind `turns`, both composer flags, and `status`. `snapshot` exposes the backend contract, including session and turn usage; `admission` and `observation` describe request/connection outcomes separately from execution.
- The optional third controller argument, `SessionArtifactMapper`, maps a published artifact to `ChatArtifact` or `null`. The default preserves identity/type and maps title, subtitle, payload, and metadata.
- On identity changes, clear content, status, and draft; dispose and recreate the transport/controller. Disposal ignores stale results and aborts observation without cancelling execution.

## Rendering contract

Rendering-only hosts import `ChatUiComponent` and supply their own state and handlers.

| Input/output                                   | Contract                                                                                                                                                      |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `turns`                                        | Required input. Turns and content render in supplied order.                                                                                                   |
| `bannerTitle`, `bannerDescription`             | Optional banner content. Omitting both hides the banner; title-to-description spacing appears only when both are present.                                     |
| `artifactRenderers`                            | Type-to-`artifactRenderer(template)` map. Templates receive payload as `$implicit`, full artifact through `let-artifact="artifact"`.                          |
| `conversationStatus`                           | Loading/error with `message`, `placement: 'conversation' \| 'assistant'`, optional action `{ id, label }`, and optional loading `reveal: 'delayed'` (300 ms). |
| `composerDisabled` / `composerEditingDisabled` | Block submissions / edits independently; both default to `false`. Editing lock preserves textarea focusability.                                               |
| `composerPlaceholder` / `mascotAssetPath`      | Defaults: `Nachricht schreiben` / `images`.                                                                                                                   |
| `messageSubmitted`                             | Emits trimmed nonempty text and `acknowledge()`. Acknowledge acceptance to clear the matching draft. No optimistic prompt is inserted.                        |
| `statusActionTriggered`                        | Emits the action's opaque ID for the host to handle.                                                                                                          |

### Content and identity

Optional `usage: ChatUsage | null` shows conversation totals below the composer, with expandable detailed counters. Omit usage to hide both views. Hosts supply all counters and `estimatedCostUsd` (decimal string or `null`, meaning unavailable). Costs and compact totals are rounded for display; tooltips retain exact values.

Content items have stable host-supplied `id` values and readonly fields. Optional item `turnId` does not determine ownership: the enclosing turn does.

| Type                      | Fields beyond `id`                                                                                                                                           |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `ChatTurn` (no item ID)   | `runKey`, ordered `content`, `status`: `prompt`, `active`, `completed`, `failed`, `cancelled`, or `unknown`.                                                 |
| `ChatTextMessage`         | `kind: 'text'`, `role: 'user' \| 'assistant'`, `text`, `isFinal`. Only explicitly final assistant answers use `true`.                                        |
| `ChatIntermediateMessage` | `kind: 'intermediate'`, `text`: user-facing progress, never provider reasoning.                                                                              |
| `ChatToolCall`            | `kind: 'tool'`, literal `name`, `status`: `requested`, `running`, `completed`, `failed`, `not_executed`, or `outcome_unknown`. Arguments/results are hidden. |
| `ChatTurnFailure`         | `kind: 'failure'`, `text`. Current error status covers a trailing failure marker; it remains in later history.                                               |
| `ChatArtifact`            | `kind: 'artifact'`, `type`, `headline`, recursive JSON `payload`; optional `subtitle` and JSON-object `metadata`.                                            |

- Share one conversation-scoped `runKey` across execution sections; independent prompts use `null`. Keep keys stable across snapshots and distinct across sessions. No section ID or prompt/run association is required.
- `active` includes admitted work awaiting execution and final text awaiting completion. Final text alone must not end busy state. Retain complete output and accepted artifacts after failure.
- User text is literal. Assistant/progress text supports headings, paragraphs, emphasis, code, lists, blockquotes, and safe HTTP(S), mail, root-relative, or fragment links. Raw HTML and unsafe schemes are not interpreted.

### Interaction behavior

- Enter submits; Shift+Enter inserts a line break. Drafts remain until acknowledgement. Pointer controls preserve focus; initialization/acknowledgement never move it. Mobile keyboard behavior depends on the browser.
- Loading uses conversation text or assistant dots; errors appear immediately. Rendering-only hosts clear assistant loading when response content appears. The controller shows no sending indicator and starts loading once the accepted prompt is visible.
- Completed runs with an explicit final answer collapse intermediate messages/tool calls once. Other runs start expanded. Final-answer bars share a details toggle; later manual choices persist for the component lifetime. Ordinary text, artifacts, and failures stay visible; artifact state survives toggles.
- New content/status normally scrolls to the bottom, even after scrolling up. Detail/artifact toggles use native anchors; positioning depends on browser scroll range. Collapsed details stay mounted but inert; focus inside them is not transferred automatically.
- Detail transitions respect reduced motion; loading animations do not. Some controls/status labels are German.

## Artifact presentation

The built-in `json` renderer displays escaped, formatted `payload.value`. Other types require explicit renderers; missing mappings show an unsupported-presentation message. Cards clip tall bodies with expand/collapse controls and no nested scrolling. Subtitles remain visible when collapsed.

| Capability field                          | Meaning                                                                                                                                              |
| ----------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `type`, `description`, `payloadSchema`    | Required type, usage guidance, and complete payload schema. `JSON_ARTIFACT_CAPABILITY` advertises `{ value: <JSON value> }`.                         |
| `titleDescription`, `subtitleDescription` | Optional header guidance, not payload-field validation. Descriptions must be nonblank and at most 2,000 characters.                                  |
| `metadataSchema`                          | Optional self-contained JSON Schema draft 2020-12. Metadata is validated separately; omission is checked as `{}`; unadvertised metadata is rejected. |

Advertise capabilities at session creation; renderer registration alone does not advertise them. Renderers receive complete data and do not fetch missing details. Metadata has no built-in rendering/actions. See the [artifact publication rules](https://github.com/roithme0/ai-service/blob/production/docs/domains/artifacts.md#publication-rules) for backend validation and retention.

## Transport and recovery

Direct transport methods: `createSession(initialization?)`, `readSession(sessionId)`, `submitPrompt(sessionId, text)`, and `observeSession(sessionId, signal)`.

| Outcome                                                | Behavior                                                                                                                                                                                                                           |
| ------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Prompt accepted                                        | Returns `{ kind: 'accepted' }` without a turn ID. Controller acknowledges the draft; only snapshots supply content.                                                                                                                |
| Admission response missing                             | Draft retained, edits allowed, submissions blocked as uncertain. No reconciliation, guessed acknowledgement, or automatic replay.                                                                                                  |
| Observation                                            | Async iterable of complete snapshots and terminal error events. Lifecycle defines turn outcomes; EOF does not mean completion. Leaving/aborting releases the reader without cancelling execution.                                  |
| Transient observation failure                          | Controller reconnects after one second for network loss, unexpected EOF, capacity limits, overflow, and internal observation errors. Sending waits for a fresh snapshot. Transport itself never retries.                           |
| Compatibility, unavailable session, malformed response | Reconnection stops. Known terminal outcomes survive observation loss.                                                                                                                                                              |
| Conversation budget exhausted                          | History stays visible; submissions stop without retry. Reads/observation remain available until expiry.                                                                                                                            |
| Errors                                                 | `SessionHttpError` includes status/kind: 405 maps to `method_not_allowed`, FastAPI 422 to `validation_error`. Network/malformed responses throw `SessionTransportError`. SSE errors remain typed `SessionEvent` values before EOF. |

`presentSession` maps independent prompts and run groups, including groups without native run IDs. Keys use session identity and presentation ordinals. Only explicit `final_answer` text becomes `isFinal: true`; unphased text is never promoted by position or outcome. Generated TypeScript/Zod schemas validate the contract, including finite recursive JSON.

## Theme

Set CSS variables on an ancestor of `ai-chat-ui`; fallback defaults preserve inherited overrides. Material styles controls; library styles are bundled.

See the [token catalog](https://github.com/roithme0/ai-service/blob/production/frontend/projects/chat-ui/ui/src/styles/_tokens.scss) and its imported semantic groups for configurable variables and defaults.

## Repository workflows

- [Development](https://github.com/roithme0/ai-service/blob/production/docs/development.md): local linking, validation, contract generation, built-package checks, and browser verification.
- [Releases](https://github.com/roithme0/ai-service/blob/production/docs/operation.md#releases): shared tags, `latest`/`alpha` channels, and publication checks. CI/Docker consume published versions rather than sibling checkout links.
