# Chat UI

`@roithme0/chat-ui` provides an Angular 22 conversation UI with optional AI Service integration. It has no Kochwiki dependency.

| Entry point                      | API                                                                                                                         |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `@roithme0/chat-ui/ui`           | `ChatUiComponent`, content/status types, artifact renderers, and capabilities. Renders host state without backend requests. |
| `@roithme0/chat-ui/conversation` | `SessionController`, `HttpSessionTransport`, snapshot mapping, and generated session types.                                 |

The root entry point exports no API. Both entry points share one version.

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

Set `mascotAssetPath="assets/chat-ui/images"`; the default is `images`, relative to the application base URL. The package supplies `mascot-idle.png` and `maskot-working.png` (spelling intentional). Any `active` turn selects the working mascot, even after final text arrives. The idle image can also serve as a favicon.

## AI Service integration

A standalone host using the scripted `demo` configuration:

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
    bannerTitle="Chat demo"
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
    new HttpSessionTransport('/api/v1', 'demo', 'demo:default'),
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

- The transport takes the URL prefix before `/agents`, configuration key, and identity string `${encodeURIComponent(issuer)}:${encodeURIComponent(subject)}` sent as `X-Application-User` on every request. Both components must be nonempty; ownership compares the decoded issuer/subject pair. The demo uses issuer `demo` and subject `default`. This temporary assertion does not authenticate the caller. The backend forwards the session owner's assertion to Kochwiki MCP separately for each turn.
- `start(initialization?)` accepts `initial_context` and `artifact_capabilities`; replacement sessions reuse them. Server validation is authoritative.
- Bind `turns`, both composer flags, and `status`. `snapshot` exposes the backend contract, including session and turn usage; `admission` and `observation` describe request/connection outcomes separately from execution.
- The optional third controller argument, `SessionArtifactMapper`, maps a published artifact to `ChatArtifact` or `null`. The default preserves identity/type and maps title, subtitle, payload, and metadata.
- On identity changes, clear content, status, and draft; dispose and recreate the transport/controller. Disposal ignores stale results and aborts observation without cancelling execution.

## Rendering contract

Rendering-only hosts import `ChatUiComponent` and supply their own state and handlers.

| Input/output                                   | Contract                                                                                                                                                      |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `bannerTitle`, `bannerDescription`, `turns`    | Required inputs. Turns and content render in supplied order.                                                                                                  |
| `artifactRenderers`                            | Type-to-`artifactRenderer(template)` map. Templates receive payload as `$implicit`, full artifact through `let-artifact="artifact"`.                          |
| `conversationStatus`                           | Loading/error with `message`, `placement: 'conversation' \| 'assistant'`, optional action `{ id, label }`, and optional loading `reveal: 'delayed'` (300 ms). |
| `composerDisabled` / `composerEditingDisabled` | Block submissions / edits independently; both default to `false`. Editing lock preserves textarea focusability.                                               |
| `composerPlaceholder` / `mascotAssetPath`      | Defaults: `Nachricht schreiben` / `images`.                                                                                                                   |
| `messageSubmitted`                             | Emits trimmed nonempty text and `acknowledge()`. Acknowledge acceptance to clear the matching draft. No optimistic prompt is inserted.                        |
| `statusActionTriggered`                        | Emits the action's opaque ID for the host to handle.                                                                                                          |

### Content and identity

Optional `usage: ChatUsage | null` shows conversation totals below the composer, with a toggle for detailed counters. The expanded panel fades the line and mascot away; Escape closes it. Omit usage to hide both views. Hosts supply all counters and `estimatedCostUsd` (decimal string or `null`, meaning unavailable). Costs and compact totals are rounded for display; tooltips retain exact values.

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
- New content/status normally scrolls to the bottom, even after scrolling up. Detail/artifact toggles use native anchors; positioning depends on browser scroll range. Chrome/Firefox anchoring verification is pending. Collapsed details stay mounted but inert; focus inside them is not transferred automatically.
- Detail transitions respect reduced motion; loading animations do not. Some controls/status labels are German.

## Artifact presentation

The built-in `json` renderer displays escaped, formatted `payload.value`. Other types require explicit renderers; missing mappings show an unsupported-presentation message. Cards clip bodies at `--ai-chat-artifact-collapsed-height` (default `18rem`) with expand/collapse controls and no nested scrolling. Subtitles remain visible when collapsed.

| Capability field                          | Meaning                                                                                                                                              |
| ----------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `type`, `description`, `payloadSchema`    | Required type, usage guidance, and complete payload schema. `JSON_ARTIFACT_CAPABILITY` advertises `{ value: <JSON value> }`.                         |
| `titleDescription`, `subtitleDescription` | Optional header guidance, not payload-field validation. Descriptions must be nonblank and at most 2,000 characters.                                  |
| `metadataSchema`                          | Optional self-contained JSON Schema draft 2020-12. Metadata is validated separately; omission is checked as `{}`; unadvertised metadata is rejected. |

Advertise capabilities at creation; renderer registration alone does not advertise them. Capabilities cannot change mid-session. Without them, model-backed sessions are text-only. Agents supply complete data; renderers do not fetch missing details. Metadata has no built-in rendering/actions. Publication does not save domain data.

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

| Property                          | Purpose                    | Default      |
| --------------------------------- | -------------------------- | ------------ |
| `--ai-chat-background`            | Container background       | `#130d0f`    |
| `--ai-chat-text`                  | General text               | `#f8eef1`    |
| `--ai-chat-banner-background`     | Banner background          | `#291c21`    |
| `--ai-chat-banner-text`           | Banner text                | `#f8eef1`    |
| `--ai-chat-user-background`       | User bubble                | `#a9004f`    |
| `--ai-chat-user-text`             | User text                  | `#ffffff`    |
| `--ai-chat-assistant-text`        | Assistant text             | General text |
| `--ai-chat-muted-text`            | Secondary/placeholder text | `#c6b4bb`    |
| `--ai-chat-accent`                | Focus/quote accent         | `#e00067`    |
| `--ai-chat-link`                  | Links                      | `#ff7aad`    |
| `--ai-chat-code-background`       | Code background            | `#251a1e`    |
| `--ai-chat-artifact-background`   | Artifact background        | `#21171b`    |
| `--ai-chat-artifact-border`       | Artifact border            | `#50363f`    |
| `--ai-chat-artifact-subtitle`     | Artifact subtitle          | `#bda9b1`    |
| `--ai-chat-artifact-heading`      | Artifact headline          | `#f8eef1`    |
| `--ai-chat-artifact-text`         | JSON text                  | `#eadde2`    |
| `--ai-chat-composer-background`   | Composer background        | `#291c21`    |
| `--ai-chat-composer-border`       | Composer border            | `#50363f`    |
| `--ai-chat-composer-text`         | Composer text              | `#f8eef1`    |
| `--ai-chat-send-background`       | Send background            | `#c00059`    |
| `--ai-chat-send-hover-background` | Send hover                 | `#df0067`    |
| `--ai-chat-send-text`             | Send text                  | `#ffffff`    |
| `--ai-chat-focus`                 | Keyboard focus ring        | `#ff9fc1`    |

## Repository workflows

- [Development](https://github.com/roithme0/ai-service/blob/production/docs/development.md): local linking, validation, contract generation, built-package checks, and browser verification.
- [Releases](https://github.com/roithme0/ai-service/blob/production/docs/operation.md#releases): shared tags, `latest`/`alpha` channels, and publication checks. CI/Docker consume published versions rather than sibling checkout links.
