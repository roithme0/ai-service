# Chat UI

`@roithme0/chat-ui` is one Angular 22 package with two public entry points. `@roithme0/chat-ui/ui` provides the controlled conversation component; `@roithme0/chat-ui/conversation` optionally provides the AI Service conversation controller and HTTP transport. The UI entry point renders ordered host-supplied text, tool activity, failure markers, and JSON-compatible artifacts, emits normalized user submissions and generic status actions, and leaves conversation state and transport orchestration to the host. It makes no backend requests.

The `/ui` entry point exports `ChatUiComponent` and the typed content, artifact renderer, submission, status, and status-action contracts. Import the component into the host component's `imports`.

```html
<ai-chat-ui
  bannerTitle="Rezept gemeinsam verbessern"
  bannerDescription="Beschreibe, was du ändern möchtest."
  [turns]="turns()"
  [artifactRenderers]="artifactRenderers"
  [composerDisabled]="pending()"
  [conversationStatus]="status()"
  (messageSubmitted)="handleMessage($event)"
  (statusActionTriggered)="handleStatusAction($event)"
/>
```

Tool content (`ChatToolCall`) has `kind: 'tool'`, stable `id`, `name`, and `status` (`requested`, `running`, `completed`, `failed`, `not_executed`, or `outcome_unknown`). Each call renders with a primary text name, the same packaged tool icon and a smaller secondary text German status label. Names render literally; arguments and result payloads are not displayed. Completed means a result was returned without explicitly reported failure. Failure content (`ChatTurnFailure`) has `kind: 'failure'`, `id`, and `text`; a trailing marker is covered by the current error status when present, and remains visible in later history.

`turns` is the required ordered collection of host-supplied `ChatTurn` values. Each group owns its ordered `content`, including interleaved artifacts, and has a required `runKey` and `status` (`prompt`, `active`, `completed`, `failed`, `cancelled`, or `unknown`). Prompts and execution groups are independent; no user-message association is required. Execution sections share one conversation-scoped `runKey`, including single-section runs; independent prompt sections use `null`. The renderer derives unique section tracking keys locally from the run key and its occurrence. There is no separate section ID in the input model. Scope run keys to the conversation so that a new session cannot inherit prior detail expansion state. Active includes accepted work waiting to start and closing work whose answer has arrived before terminal completion. Rendering-only hosts supply these values independently of any backend. The component renders each turn and its content in order. Item `turnId` remains optional for rendering-only hosts; ownership is determined by the enclosing turn.

Completed turns with an explicitly final assistant text and at least one intermediate message or tool call start with those details collapsed. A single accessible details button appears immediately after the first explicitly final assistant text. Active, failed and unknown turns retain all details and have no toggle, even when final text has arrived. User text, ordinary and final assistant text, artifacts and failures remain visible; artifacts retain their order and local renderer/card state across toggles. Recoverable tool failures do not block collapse in a completed turn. Manual expansion is remembered by run key for the component lifetime, including subsequent submissions, and resets on component recreation. Expansion and collapse animate each detail item together with its spacing over 200 ms; reduced-motion preferences disable this transition. Collapsed details remain mounted but are inert and hidden from assistive technology. Manual toggles do not request scrolling or restore scroll offsets; the browser may clamp the offset when content becomes shorter. Native scroll anchoring is disabled for the history. Toggle changes do not trigger live-content bottom scrolling. Automatic collapse has no special focus transfer for a focused link inside the hidden details; this edge case is accepted without additional handling.

Text content has readonly `kind`, `id`, `role` (`user` or `assistant`), and `text` fields, plus required `isFinal: boolean`. Only an explicitly identified final assistant answer has `isFinal: true`; user text and unspecified assistant text have `false`. The marker does not depend on message position or turn outcome and determines detail-toggle eligibility and button placement. Artifacts have readonly `kind`, `id`, `type`, `headline`, optional `subtitle`, and recursive `JsonValue` payload fields. Identity is host-supplied and should remain stable when the collection changes. User text is always rendered literally. Assistant text supports a constrained Markdown subset: headings, paragraphs, emphasis, strong text, inline and fenced code, ordered and unordered lists, blockquotes, and safe HTTP(S), mail, root-relative, or fragment links. Raw HTML and unsafe link schemes are not interpreted.

Intermediate assistant content (`ChatIntermediateMessage`) has readonly `kind: 'intermediate'`, `id`, and `text`. It uses the same safe Markdown renderer and primary text styling as final assistant messages and appears in recorded order among tool calls and artifacts, including after failed turns. These are user-facing progress explanations; provider reasoning is not displayed. Complete messages appear live and retain their supplied styling permanently. Final messages alone do not finish the busy state; terminal success is authoritative. All complete output and accepted artifacts survive later turn failure.

Map artifact type discriminators to typed Angular templates with `artifactRenderer(template)`. The built-in `json` type renders the escaped, formatted `payload.value`. An absent mapping for any other type shows an unsupported-presentation message; it does not silently select JSON. The library frames every artifact and clips renderer bodies above `--ai-chat-artifact-collapsed-height` (default `18rem`) with German expand/collapse controls and no nested scrolling area.

The component trims a valid submission and emits it once as a `ChatSubmission`. It retains the draft until the host calls `acknowledge`, so the visible composer can remain truthful to backend acceptance. It never adds that text to `turns`; the host updates or replaces its own collection in response. Enter submits, while Shift+Enter adds a line break. New content and status changes smoothly scroll the conversation history to the bottom, including when a delayed status becomes visible, even if the user had scrolled up.

`conversationStatus` accepts a host-controlled loading or error state, its placement, and an optional generic action. Conversation loading renders as text; assistant loading renders as the supplied three-dot animation, with the status message as its accessible label. Conversation loading text fades in over 180 ms; the dots use only their SVG animation. Dots inherit the muted theme color. A reusable Angular component uses the supplied animated SVG as its external template; the animation does not vary with the reduced-motion setting. Loading states can opt into `reveal: 'delayed'`: the UI reserves a line and waits 300 ms before revealing the loading content. Replacing the status cancels the pending reveal. The conversation controller shows no indicator while sending. It starts assistant loading immediately once the accepted user message is displayed in history. Errors appear immediately without animation. Changing the conversation loading label restarts its fade. Animations run regardless of the reduced-motion setting. Rendering-only hosts own the loading lifetime: clear assistant loading as soon as any response content from that turn can be displayed. `composerDisabled` blocks submissions. `composerEditingDisabled` separately blocks text edits while keeping the textarea enabled and focusable. The controller blocks editing only while submission admission is pending. Acceptance unlocks editing before acknowledging the message, so the next draft can be written during the assistant response. A missing admission response retains the draft and blocks further submissions while allowing edits; the controller does not reconcile acceptance. Cancellable edits are prevented before input; other edits restore the retained draft. The send button remains disabled while submissions or edits are blocked, and the textarea exposes its editing lock through `aria-disabled`. This avoids disabling the focused textarea during sending; mobile keyboard persistence still depends on the browser. The composer does not move focus on initialization, state changes, or message acknowledgement; focus remains under user control. Status actions emit their opaque ID to the host; neither contract contains backend- or recipe-specific types.

## Assets

The package includes reusable library assets under `public/`, including
`public/images/mascot-idle.png` and `public/images/maskot-working.png`.
The demo application serves the same source folder (`projects/chat-ui/public`)
and uses `images/mascot-idle.png` as its favicon.
Angular consumer apps can copy the packaged assets by adding this
entry to their application's build `assets` array in `angular.json`:

```json
{
  "glob": "**/*",
  "input": "node_modules/@roithme0/chat-ui/public",
  "output": "assets/chat-ui"
}
```

Set `mascotAssetPath="assets/chat-ui/images"` on `<ai-chat-ui>` when using this
asset mapping. The default path is `images`, relative to the application's base
URL. The decorative duck sits above the composer's right edge and shows the
working image while any supplied turn has status `active`, including after
final text arrives until the turn finishes. It returns to idle for completed,
failed, or unknown turns; loading indicators and composer locks do not select
the working image.

Use `assets/chat-ui/images/mascot-idle.png` as an image URL or as a favicon:

```html
<link rel="icon" type="image/png" href="assets/chat-ui/images/mascot-idle.png" />
```

## AI Service conversation integration

Import rendering components from `@roithme0/chat-ui/ui` and conversation support from `@roithme0/chat-ui/conversation`. The root entry point exports no API. Both entry points share the package version and release lifecycle.

A complete minimal standalone host (with the Material theme described below):

```typescript
import { Component, OnInit, OnDestroy, signal } from '@angular/core';
import { ChatUiComponent, type ChatSubmission } from '@roithme0/chat-ui/ui';
import {
  SessionController,
  HttpSessionTransport,
  type SessionViewState,
} from '@roithme0/chat-ui/conversation';

@Component({
  selector: 'app-chat',
  imports: [ChatUiComponent],
  template: ` <ai-chat-ui
    bannerTitle="Chat demo"
    bannerDescription="Any text advances the scripted sequence."
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
    void this.controller.start();
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

The base URL is the prefix immediately before `/agents`; the demo uses `/api/v1`. The transport takes a configuration key and an explicit application identity as `X-Application-User`. Server validation is authoritative. Supply initial context and advertised artifact capabilities to `start(initialization)` when needed; replacement sessions retain that initialization.

The controller receives complete backend snapshots and derives UI content through `presentSession`. Its optional third constructor argument is a `SessionArtifactMapper`, which receives the native artifact envelope and returns a `ChatArtifact` or `null` to omit it. The default `presentSessionArtifact` preserves artifact identity and type and unwraps its presentation payload. The host owns view-state binding and renderer registration. See session lifecycle and recovery below for admission and observation behavior.

For selected-user changes, clear visible content, status and draft, dispose the old controller and create a new transport and controller for the selected identity. Disposal aborts observation and ignores stale asynchronous results; it does not cancel backend execution. Sessions are not transferred between identities.

## Built-package verification

From `frontend`, run `npm run build:chat-ui`, then `node scripts/check-chat-ui-package.mjs`. This checks actual package exports and declarations with ordinary package resolution, exercises the built conversation module, checks required application identity and verifies that the root exports no API. Workspace source aliases are not used.

## Host theme

The host must install compatible Angular Material and CDK versions and provide an Angular Material theme. For example, a host can import a prebuilt theme in its global stylesheet:

```css
@import '@angular/material/prebuilt-themes/magenta-violet.css';
```

The library uses Angular Material's `MatIconRegistry` to register packaged SVGs in the `ai-chat` namespace: the supplied custom outline `send` icon and selected Material Icons (`retry`, `tts`, and `add-file`). Its controls reference them through names such as `ai-chat:send`. A shared `ai-chat:tool` wrench SVG renders all tool calls. Hosts do not need to load the Material Icons font or register these icons. The Material Icons source and their Apache 2.0 terms are documented in `MATERIAL_ICONS_LICENSE` in the published package.

Set these CSS variables on an ancestor of `ai-chat-ui`:

| Property                          | Purpose                        | Default      |
| --------------------------------- | ------------------------------ | ------------ |
| `--ai-chat-background`            | Container background           | `#130d0f`    |
| `--ai-chat-text`                  | General text                   | `#f8eef1`    |
| `--ai-chat-banner-background`     | Banner background              | `#291c21`    |
| `--ai-chat-banner-text`           | Banner text                    | `#f8eef1`    |
| `--ai-chat-user-background`       | User bubble background         | `#a9004f`    |
| `--ai-chat-user-text`             | User bubble text               | `#ffffff`    |
| `--ai-chat-assistant-text`        | Assistant text                 | General text |
| `--ai-chat-muted-text`            | Secondary and placeholder text | `#c6b4bb`    |
| `--ai-chat-accent`                | Focus and quote accent         | `#e00067`    |
| `--ai-chat-link`                  | Assistant link text            | `#ff7aad`    |
| `--ai-chat-code-background`       | Assistant code background      | `#251a1e`    |
| `--ai-chat-artifact-background`   | Artifact card background       | `#21171b`    |
| `--ai-chat-artifact-border`       | Artifact card border           | `#50363f`    |
| `--ai-chat-artifact-subtitle`     | Artifact subtitle              | `#bda9b1`    |
| `--ai-chat-artifact-heading`      | Artifact headline              | `#f8eef1`    |
| `--ai-chat-artifact-text`         | JSON presentation text         | `#eadde2`    |
| `--ai-chat-composer-background`   | Composer field background      | `#291c21`    |
| `--ai-chat-composer-border`       | Composer field border          | `#50363f`    |
| `--ai-chat-composer-text`         | Composer field text            | `#f8eef1`    |
| `--ai-chat-send-background`       | Send control background        | `#c00059`    |
| `--ai-chat-send-hover-background` | Send control hover background  | `#df0067`    |
| `--ai-chat-send-text`             | Send control foreground        | `#ffffff`    |
| `--ai-chat-focus`                 | Keyboard focus ring            | `#ff9fc1`    |

The component inherits typography. Its chat-specific styles are compiled into the library, while the host-provided Angular Material theme styles its Material controls. CSS variable defaults are `var()` fallback values and do not mask inherited host values. The library has no Kochwiki dependency.

## GitHub Packages releases

The library publishes to `https://npm.pkg.github.com` and is associated with `roithme0/ai-service`. The `Build and publish app and chat UI` workflow builds the library on pull requests and pushed `v`-prefixed version tags in its distinct `build-chat-ui` job, uploading the built package as a workflow artifact. The `publish-chat-ui` job runs only for release tags and downloads that same artifact. Only this publish job receives `packages: write` permission. The same workflow publishes both Docker images through separate application jobs; every release publishes all three artifacts from the same commit, even when a component has not changed.

The tag determines the published version and npm channel: `v1.2.0` publishes `1.2.0` under `latest`; `v1.2.0-alpha` or `v1.2.0-alpha.123` publishes the corresponding prerelease under `alpha`. Tags must start with `v` followed by three numeric version parts, optionally followed by `-alpha` or `-alpha.N`, where `N` contains one or more digits. Numeric parts cannot have leading zeroes except for `0`; other suffixes are rejected. The leading `v` is stripped from published versions. Release tags are validated before frontend dependency installation and the library build. The publish job sets the version in `dist/chat-ui/package.json` and publishes using its `GITHUB_TOKEN` with an explicit npm dist-tag. The source package keeps the local placeholder version `0.0.0` and is not modified by the workflow.

To release the repository, commit the changes, then tag that commit and push the tag. For example:

```powershell
git tag v1.2.0
git push origin v1.2.0
```

For an alpha release, use a new prerelease version tag from the repository root. No package version edit is required:

```powershell
git tag v1.3.0-alpha.1
git push origin v1.3.0-alpha.1
```

Each release needs a new version; choose the next shared version based on changes to either the application or library, including breaking changes. Both publication jobs wait for the application and library builds to succeed, including the application build's contract checks and backend tests. A failed build prevents all publication. Publication remains independent between jobs, so a registry failure can still leave a partial release; check the entire workflow succeeded before treating a release as complete. Kochwiki has read access under the package's **Manage Actions access** settings and consumes the package from GitHub Packages. Its CI passes the repository's short-lived `GITHUB_TOKEN` to Docker as a BuildKit secret.

## Local development with Kochwiki

Use a direct local link for interactive development. No global npm link is created.

Build the library once before creating the link, then leave its watcher running:

```powershell
# In ai-service/frontend:
npm run build:chat-ui
npm run watch:chat-ui
```

In another terminal, link Kochwiki directly to the compiled Angular package and start its development server:

```powershell
# In kochwiki-v2/frontend:
npm run link:chat-ui
npm start
```

Kochwiki preserves the package symlink and excludes `@roithme0/chat-ui` from development-server prebundling, so changes written to `dist/chat-ui` trigger a consumer rebuild and browser reload. Running `npm install` or `npm ci` in Kochwiki restores the declared registry dependency; rerun `npm run link:chat-ui` afterward when local library development is needed.

Docker, CI, and production builds always install the declared GitHub Packages version. They do not use the sibling checkout or its link.

## Browser verification

Run the backend on port 8004 and `npm run start:app` in `frontend`, then open `http://localhost:4204` at a portrait-phone viewport. The host creates an empty `demo` session and advances a scripted sequence through the real backend. No model credentials or Kochwiki access is required; see [frontend setup](../../README.md) for commands.

Submit arbitrary text to check the loading state and introduction, then both JSON artifacts, titled `demo.greeting` and `demo.greetings` (a list of 30 greetings) in the same turn, then a scripted error and completion guidance on the following message. The error's “Demo-Aktion (ohne Funktion)” button leaves the state unchanged. The demo host explicitly selects JSON presentation for both artifacts before the assistant reply. Check that the list starts collapsed and that “Mehr anzeigen” and “Weniger anzeigen” expand and collapse it. One more message triggers a frontend-only simulated 405 compatibility error without a retry action; the backend continues accepting messages. Refresh to restart with empty history; no dedicated restart button is provided. Generic error recovery actions remain available when failures occur. Also check that history scrolls without moving the page, the composer remains at the bottom through viewport-height changes, Enter and the send control submit once, Shift+Enter creates a line break, and long content causes no horizontal page scrolling.

## Advertising presentation capabilities

The UI entry point exports `ChatArtifactCapability` and
`JSON_ARTIFACT_CAPABILITY`, including the shared JSON renderer's usage description
and payload schema. Consumer frontends select the capabilities they support and
supply them beside caller context when creating a model-backed session:

```typescript
import { JSON_ARTIFACT_CAPABILITY } from '@roithme0/chat-ui/ui';
import { HttpSessionTransport } from '@roithme0/chat-ui/conversation';

const transport = new HttpSessionTransport('/api/v1', 'demo', 'demo:default');
const session = await transport.createSession({
  initial_context: { selectedItem: item },
  artifact_capabilities: [JSON_ARTIFACT_CAPABILITY],
});
```

The AI Service supplies the agent with a local `present_artifact` tool. The agent
chooses when presentation helps and sends complete data; the renderer does not
fetch missing details. JSON presentation uses type `json` and payload
`{ value: <any JSON value> }`. With the default `presentSessionArtifact` mapper, a backend
presentation title becomes the card headline, and its optional `subtitle` appears
as plain secondary text beneath it. The subtitle remains visible when the body
is collapsed. Omitting capabilities keeps a
model-backed session text-only. Custom renderer registration does not itself
advertise a capability: the consumer must select its matching description and
schema explicitly. Capability changes during a session are not supported.

Capabilities can include optional `titleDescription` and `subtitleDescription`
to tell the agent which values belong in the header. For example, a foodstuff
capability can specify the foodstuff name as its title and its brand as the
subtitle, omitted when absent. This is agent guidance rather than validation
against the payload. Descriptions must be nonblank and at most 2,000 characters.
The shared JSON capability includes guidance for a short descriptive title and
an optional explanatory subtitle.

Capabilities may also advertise an optional `metadataSchema`, a self-contained
JSON Schema (draft 2020-12). The agent follows its field descriptions when
supplying the optional `metadata` object to `present_artifact`. The service
validates metadata separately from the presentation payload and rejects metadata
for capabilities that do not advertise it. Omitted metadata is validated as an
empty object, so schema-required fields remain required. The default mapper
passes metadata to `ChatArtifact.metadata`; custom templates access it through
`let-artifact="artifact"`. Metadata has no built-in rendering or action behavior;
the consumer frontend interprets it and owns any domain actions.

## Session HTTP transport

The `/conversation` entry point exports `HttpSessionTransport` and its
`SessionTransport` interface for the Pydantic AI session API used by the demo
application at `/api/v1`. Kochwiki uses the same contract at `/api/v1`
with configuration key `kochwiki`.

```ts
const transport = new HttpSessionTransport('/api/v1', 'demo', 'demo:default');
const session = await transport.createSession({
  initial_context: { selectedItem: item },
  artifact_capabilities: [JSON_ARTIFACT_CAPABILITY],
});
const snapshot = await transport.readSession(session.session_id);
await transport.submitPrompt(session.session_id, 'Please update this item.');
```

`submitPrompt()` returns `{ kind: 'accepted' }` after admission, without a turn ID.
`observeSession(sessionId, signal)` returns an async iterable of complete snapshot
events across turns and terminal observation error events. Snapshots preserve the
backend's ordered `history` of independent user prompts and run groups, including
empty groups whose native run ID is not yet available. Observation errors describe
the connection; turn outcomes come from snapshot lifecycle status. Clean EOF means
the observation ended, not that a turn completed. Aborting or leaving the iterable
releases the reader and does not cancel execution. The transport does not retry;
`SessionController` owns observation reconnection. There are no optimistic messages
or frontend lifecycle reconstruction.

HTTP failures throw `SessionHttpError` with status and kind; HTTP 405 uses
`method_not_allowed` independently of its response body, and FastAPI 422 responses
use `validation_error`. Network and malformed-response failures throw
`SessionTransportError`. Observation error frames remain typed `SessionEvent`
values, followed by the end of the iterable. The transport uses the generated
schemas directly. The backend response schemas require explicit discriminators
and describe recursive finite JSON values for context and artifact data.

The `conversation/generated` contract is generated from an isolated
FastAPI app mounting `app.agentic.http.create_session_router(lambda: {})`, using
the existing `@hey-api/openapi-ts` TypeScript and Zod plugins. It does not depend
on production mounting. Backend regression
coverage compares its OpenAPI document with the actual router.

The generation and drift-check commands cover this contract. From
`frontend` in PowerShell:

```powershell
$env:PYTHON = (Resolve-Path ../backend/.venv/Scripts/python.exe).Path
npm.cmd run generate:conversation-contract
npm.cmd run check:conversation-contract
```

## Session lifecycle and recovery

`SessionController` owns prompt submission, session observation and recovery.
`HttpSessionTransport` handles HTTP and SSE, and `presentSession` projects the
backend snapshot into the rendering component's view model.

Create a `SessionController(transport, publish)` and bind its `SessionViewState.turns`, composer flags and `status` to the controlled component. Call `start(initialization?)`, forward submissions to `submit(text, acknowledge)`, forward status actions to `performAction(id)`, and call `dispose()` on teardown. `snapshot` exposes the latest generated `PresentedSession` contract; `admission` and `observation` report request and connection outcomes separately from its authoritative execution lifecycles. `SessionArtifactMapper` receives the generated artifact type and can omit artifacts with `null`; the default `presentSessionArtifact` maps its typed payload envelope directly.

A snapshot with `error: 'conversation_limit_reached'` keeps history visible, disables submission, and shows `Conversation limit reached` through the existing assistant error status. An admission rejection with that kind also blocks submission while observation continues. Exhaustion has no retry action; reads and observation remain available until session expiry.

Admission success calls the submission acknowledgement without inserting a prompt. Only observer snapshots supply conversation content. A missing admission response retains the draft, reports uncertainty and disables submission; healthy observation continues, without reconciliation reads, text matching, retries or guessed acknowledgement. Disposal aborts observation and ignores late HTTP results, without cancelling backend execution.

`presentSession` derives ordered prompt fragments and execution groups directly from the native snapshot. Run keys use session identity and presentation ordinals, never prompt text or run IDs as application execution identity; section tracking keys remain internal to the renderer. Completed runs anchor shared detail toggles on the first explicit final answer, otherwise the last unphased text; commentary alone is not an answer. Failed, cancelled and execution-uncertain groups remain expanded. Known terminal lifecycle outcomes remain intact after observation loss. The controller reconnects after a one-second delay on network failures, unexpected EOF, observer capacity limits, overflow and internal observation errors. Sending stays disabled until a fresh snapshot arrives; its lifecycle determines whether execution is still active or finished. Compatibility failures, unavailable sessions and malformed responses stop reconnection. Disposal cancels pending reconnection. Observation recovery never resubmits a prompt or resolves uncertain admission.
