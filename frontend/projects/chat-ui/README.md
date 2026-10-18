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

`turns` is the required ordered collection of host-supplied `ChatTurn` values. Each turn owns its ordered `content`, including interleaved artifacts, and has a stable `id`, `userMessageId` referencing its initiating user text, and `status` (`active`, `completed`, `failed`, or `unknown`). Active includes accepted work waiting to start and closing work whose answer has arrived before terminal completion. Rendering-only hosts supply these values independently of any backend. The component renders each turn and its content in order. Item `turnId` remains optional for rendering-only hosts; ownership is determined by the enclosing turn.

Completed turns with an explicitly final assistant text and at least one intermediate message or tool call start with those details collapsed. A single accessible details button appears immediately after the first explicitly final assistant text. Active, failed and unknown turns retain all details and have no toggle, even when final text has arrived. User text, ordinary and final assistant text, artifacts and failures remain visible; artifacts retain their order and local renderer/card state across toggles. Recoverable tool failures do not block collapse in a completed turn. Manual expansion is remembered by turn ID for the component lifetime, including subsequent submissions, and resets on component recreation. Expansion reveals the details before smoothly aligning the first timeline item with the history viewport top, within its scroll range. Collapse preserves the current scroll offset, clamped to the shorter history. Toggle changes do not trigger live-content bottom scrolling.

Text content has readonly `kind`, `id`, `role` (`user` or `assistant`), and `text` fields, plus required `isFinal: boolean`. Only an explicitly identified final assistant answer has `isFinal: true`; user text and unspecified assistant text have `false`. The marker does not depend on message position or turn outcome and determines disclosure eligibility and button placement. Artifacts have readonly `kind`, `id`, `type`, `headline`, optional `subtitle`, and recursive `JsonValue` payload fields. Identity is host-supplied and should remain stable when the collection changes. User text is always rendered literally. Assistant text supports a constrained Markdown subset: headings, paragraphs, emphasis, strong text, inline and fenced code, ordered and unordered lists, blockquotes, and safe HTTP(S), mail, root-relative, or fragment links. Raw HTML and unsafe link schemes are not interpreted.

Intermediate assistant content (`ChatIntermediateMessage`) has readonly `kind: 'intermediate'`, `id`, and `text`. It uses the same safe Markdown renderer and primary text styling as final assistant messages and appears in recorded order among tool calls and artifacts, including after failed turns. These are user-facing progress explanations; provider reasoning is not displayed. Complete messages appear live and retain their supplied styling permanently. Final messages alone do not finish the busy state; terminal success is authoritative. All complete output and accepted artifacts survive later turn failure.

Map artifact type discriminators to typed Angular templates with `artifactRenderer(template)`. The built-in `json` type renders the escaped, formatted `payload.value`. An absent mapping for any other type shows an unsupported-presentation message; it does not silently select JSON. The library frames every artifact and clips renderer bodies above `--ai-chat-artifact-collapsed-height` (default `18rem`) with German expand/collapse controls and no nested scrolling area.

The component trims a valid submission and emits it once as a `ChatSubmission`. It retains the draft until the host calls `acknowledge`, so the visible composer can remain truthful to backend acceptance. It never adds that text to `turns`; the host updates or replaces its own collection in response. Enter submits, while Shift+Enter adds a line break. New content and status changes smoothly scroll the conversation history to the bottom, including when a delayed status becomes visible, even if the user had scrolled up.

`conversationStatus` accepts a host-controlled loading or error state, its placement, and an optional generic action. Conversation loading renders as text; assistant loading renders as the supplied three-dot animation, with the status message as its accessible label. Conversation loading text fades in over 180 ms; the dots use only their SVG animation. Dots inherit the muted theme color. A reusable Angular component uses the supplied animated SVG as its external template; the animation does not vary with the reduced-motion setting. Loading states can opt into `reveal: 'delayed'`: the UI reserves a line and waits 300 ms before revealing the loading content. Replacing the status cancels the pending reveal. The conversation controller shows no indicator while sending. It starts assistant loading immediately once the accepted user message is displayed in history. Errors appear immediately without animation. Changing the conversation loading label restarts its fade. Animations run regardless of the reduced-motion setting. Rendering-only hosts own the loading lifetime: clear assistant loading as soon as any response content from that turn can be displayed. `composerDisabled` blocks concurrent submissions. Set `focusOnReady` to focus the composer once when it first becomes enabled, provided focus has not moved to another control in the meantime. Status actions emit their opaque ID to the host; neither contract contains backend- or recipe-specific types.

## AI Service conversation integration

The root entry point exports no API. This is a breaking import migration: replace root imports with `@roithme0/chat-ui/ui`. Import conversation support from `@roithme0/chat-ui/conversation`. Upgrade consumer imports together with the package; there are no compatibility re-exports. Both entry points share the existing package version and release lifecycle.

A complete minimal standalone host (with the Material theme described below):

```typescript
import { Component, OnInit, OnDestroy, signal } from '@angular/core';
import { ChatUiComponent, type ChatSubmission } from '@roithme0/chat-ui/ui';
import {
  AgentConfiguration,
  ConversationController,
  HttpConversationTransport,
  presentJsonArtifact,
  type ConversationViewState,
} from '@roithme0/chat-ui/conversation';

@Component({
  selector: 'app-chat',
  imports: [ChatUiComponent],
  template: ` <ai-chat-ui
    bannerTitle="Chat demo"
    bannerDescription="Any text advances the scripted sequence."
    [turns]="chat().turns"
    [composerDisabled]="chat().composerDisabled"
    [conversationStatus]="chat().status"
    (messageSubmitted)="submit($event)"
    (statusActionTriggered)="act($event)"
  />`,
})
export class ChatHost implements OnInit, OnDestroy {
  readonly chat = signal<ConversationViewState>({
    turns: [],
    composerDisabled: true,
    status: null,
  });
  private readonly controller = new ConversationController(
    new HttpConversationTransport('/api/v1', AgentConfiguration.demo, 'demo:default'),
    (state) => this.chat.set(state),
    presentJsonArtifact,
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

The required base URL is the prefix immediately before `/agents`: `/api/v1` yields `/api/v1/agents/demo/sessions`; `/ai/api/v1/` yields `/ai/api/v1/agents/demo/sessions`. Trailing joining slashes are normalized; another `/api/v1` is never appended. Absolute URLs use the same joining behavior. Normal deployment uses a same-origin relative prefix.

`AgentConfiguration` exports the backend-derived `demo` and `kochwiki` values, plus the derived union type of the same name. Arbitrary string keys are rejected by the TypeScript contract. Known keys do not guarantee runtime availability; the server can return `agent_unavailable`.

The transport binds the URL, agent key, and required third constructor argument for application identity, and optional fourth constructor argument for initialization input. Omitted input sends `{ input: {} }`; supplied input uses `{ input: suppliedInput }`. Replacement sessions use the same transport settings. Server validation is authoritative, and configurations requiring domain input can reject an empty input. No recipe types or fixtures are packaged.

The controller's optional third constructor argument is an `ArtifactMapper`. It receives the full `ArtifactResponse` envelope and returns a `ChatArtifact` or `null` to omit it. `presentArtifact` is the default mapper: it preserves the advertised type and identity and unwraps the backend presentation payload `{ title, payload }`. `presentJsonArtifact` is an explicit adapter for hosts such as the deterministic demo that deliberately present arbitrary tool payloads using type `json` and `{ value: originalPayload }`; the controller follows the backend timeline exactly and maps the envelope embedded in each artifact item, preserving tool/artifact placement even without a final assistant answer. The host owns view-state binding, introductory text and custom renderer registration.

Session snapshots contain session identity, expiry, sequence and ordered `turns`, with no parallel messages, artifacts or timeline collections. Each turn owns its ordered `timeline`, including its initiating user message and self-contained artifact envelopes, plus `turn_id`, `user_message_id` and precise `status`: `pending`, `in_progress`, `closing`, `completed`, `generation_failed` or `conflict`. These records are the sole snapshot lifecycle contract. The backend projects initiating user identities from its authoritative timeline, admission from its internal active turn and terminal outcomes from retained history. Timeline messages carry required `is_final`, projected only from retained explicit final records and mapped directly to UI `isFinal`. Intermediate messages keep their separate kind. Terminal outcomes take precedence over received final text; final content and its marker survive later failure. The controller maps pending, in-progress and closing work to UI `active`, and generation failure or conflict to UI `failed`, without reconstructing associations or inferring completion from answer text. Observer interruption marks only the observed active turn `unknown` and retains received content. The accepted user message is placed in its acknowledged turn immediately, using a provisional message identity until the first snapshot supplies the authoritative identity. If observation fails before that snapshot, this turn and message remain visible with an unknown outcome.

The supported HTTP contract is this repository's AI Service conversation API. `ConversationTransport` exposes `generateTurn` for accepted start identity and `observeTurn` as an abortable async iterable of typed stream events. The HTTP transport validates generated runtime schemas for response bodies and decoded SSE events, and never reconnects automatically. The controller owns snapshot consistency checks for every transport, including custom ones: session ownership, initiating user anchors, turn/item identity uniqueness, and embedded artifact ownership. Snapshot checks, upserts, and built-in tool/failure presentation IDs use one shared timeline identity function. Stateful stream ordering and sequence checks remain in the controller. The controller retains one turn collection in the API timeline shape and derives the UI turns from it. Acceptance, snapshots, timeline upserts, closing, terminal outcomes, and observation loss all update this collection; there is no separate lifecycle patch on UI turns or closing flag. Its internal status also permits `unknown` for unfinished work whose observation was lost, while preserving already known terminal outcomes. The controller first attaches to its accepted turn, applies the retained snapshot, and inserts or replaces items within the supplied turn by stable identity and turn-local position. Invalid ownership, identity or position ends observation. The controller derives reconciliation users from these timelines and maps each supplied turn into a UI turn with its own ordered content. There is no separate flat content input. Artifact envelopes are available atomically with their rows. The controller hides assistant loading once the current turn has a visible intermediate message, tool call, artifact, answer or failure. An artifact omitted by the host mapper does not count as visible output; previous-turn content does not suppress a new turn?s indicator. Once hidden, it stays hidden for that turn. Backend closing also hides the indicator, including when supplied in the initial snapshot. Stream closing and terminal events derive from the same immutable snapshot as their preceding timeline upserts, so final output is delivered before terminal completion. The composer stays disabled until typed terminal state; EOF, malformed events, and observation loss retain output and report an unknown outcome without reconnect or retry actions.

Append/start request uncertainty uses authoritative session state once to avoid duplicate execution. Start recovery considers the latest submitted turn; a newly pending turn cannot be mistaken for an older terminal one, and no automatic retry is introduced. This is separate from observer interruption: no read or replacement request restores a lost observer. `start()` creates a fresh session; `dispose()` and replacement sessions abort observation and ignore stale callbacks while backend work continues. There is no resume API, refresh recovery, browser session persistence, generation retry, or cancellation control. The `/ui` entry point remains entirely controlled and network-independent.

`HttpConversationTransport(apiBaseUrl, configuration, applicationUser, input?)` requires an explicit application identity. Every request, including SSE observation, carries it as `X-Application-User`. The backend accepts a `source:id` value with exactly one colon and non-empty portions without whitespace; prefixes are unrestricted and users are not looked up. Missing or malformed headers return HTTP 422 with a typed `request_validation` error. This trusted-LAN identity is not authenticated, and the backend binds each created session to that exact identity. Reads, messages, turn starts, and SSE observation require the same owner; another identity receives the existing HTTP 404 `unknown` error. Changing the caller identity does not transfer sessions or cancel admitted work. Create a transport for the host's selected identity; the demo uses `demo:default`.

For selected-user changes, the host must immediately clear its visible content, status, and draft, dispose the previous controller, and discard it. `dispose()` invalidates pending request callbacks and aborts observation; it does not publish an empty view or cancel backend work. Require a selected user before creating a conversation. Construct a fresh transport and controller using the new stable identity (Kochwiki uses `kochwiki:<stable-user-id>`), then start a fresh conversation when the host needs one. Do not reuse the previous transport, mutate its identity, or resume its session when returning to a previously selected user.

Expected routing is host frontend ? same-origin backend/proxy ? AI Service gateway. Relays must forward `X-Application-User`, preserve response bodies and status codes, allow agent-turn durations, and avoid automatic retries of state-changing message/turn requests. Consumer relay implementation and authentication/session authorization are deferred. Same-origin routing is not an authorization guarantee.

## Built-package verification

From `frontend`, run `npm run build:chat-ui`, then `node scripts/check-chat-ui-package.mjs`. This checks actual package exports and declarations with ordinary package resolution, exercises the built conversation module, rejects arbitrary configuration keys and checks that the root exports no API. Workspace source aliases are not used.

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

The tag determines the published version and npm channel: `v1.2.0` publishes `1.2.0` under `latest`; `v1.2.0-alpha` or `v1.2.0-alpha.123` publishes the corresponding prerelease under `alpha`. Tags must start with `v` followed by three numeric version parts, optionally followed by `-alpha` or `-alpha.N`, where `N` contains one or more digits. Numeric parts cannot have leading zeroes except for `0`; other suffixes are rejected. The leading `v` is stripped from published versions. Prefix-free tags and the old `app-v*` and `chat-ui-v*` tags do not trigger releases. Release tags are validated before frontend dependency installation and the library build. The publish job sets the version in `dist/chat-ui/package.json` and publishes using its `GITHUB_TOKEN` with an explicit npm dist-tag. The source package keeps the local placeholder version `0.0.0` and is not modified by the workflow.

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

Each release needs a new version; choose the next shared version based on changes to either the application or library, including breaking changes. The first shared version should advance beyond the previously released versions of both components. Both publication jobs wait for the application and library builds to succeed, including the application build's contract checks and backend tests. A failed build prevents all publication. Publication remains independent between jobs, so a registry failure can still leave a partial release; check the entire workflow succeeded before treating a release as complete. Kochwiki has read access under the package's **Manage Actions access** settings and consumes the package from GitHub Packages. Its CI passes the repository's short-lived `GITHUB_TOKEN` to Docker as a BuildKit secret.

## Local development with Kochwiki

After Kochwiki has migrated to the published package name, use a direct local link for interactive development. No global npm link is created.

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

## Legacy local tarball handoff

From `ai-service/frontend`:

```powershell
npm ci
npm run pack:chat-ui
```

This builds a partially compiled Angular package under `dist/chat-ui` and creates `dist/roithme0-chat-ui-0.0.0.tgz`. Angular common/core/platform-browser and Angular Material/CDK are peer dependencies rather than bundled runtimes. The package contains the public declarations, compiled component styles, packaged SVG icon definitions, and library JavaScript. The application remains independently buildable with `npm run build:app`.

From the common parent directory containing both repositories:

```powershell
New-Item -ItemType Directory -Force kochwiki-v2/frontend/vendor
Copy-Item -LiteralPath ai-service/frontend/dist/roithme0-chat-ui-0.0.0.tgz -Destination kochwiki-v2/frontend/vendor/
Set-Location kochwiki-v2/frontend
npm install ./vendor/roithme0-chat-ui-0.0.0.tgz
npm run build -- --configuration production --progress=false
```

When migrating from the original package name or the artifact-renderer POC, remove the old dependency, update UI imports to `@roithme0/chat-ui/ui`, and adapt the host to the controlled `content` input and `messageSubmitted` output before running its build. Run the consumer's focused tests for its current chat host after that migration; they should cover message projection and submission orchestration rather than the removed POC renderer. This library does not prescribe a consumer test-file path.

The installed dependency points to the copied tarball in Kochwiki's build context. Keep the tarball and updated manifest/lockfile together so `npm ci` and Docker builds do not require the AI Service checkout. Do not install using a source alias, symlink, force flag, or sibling source import.

Local builds always use the placeholder version. Rebuild and pack after changing the library:

```powershell
# In ai-service/frontend:
npm run pack:chat-ui
```

Rebuilding alone does not update the legacy Kochwiki tarball installation. Repeatedly installing a changed tarball with the same filename and version can reuse an old installed copy. Prefer the direct-link workflow after the registry migration.

## Browser verification

Run the backend on port 8004 and `npm run start:app` in `frontend`, then open `http://localhost:4204` at a portrait-phone viewport. The host creates an empty `demo` session and advances a scripted sequence through the real backend. No model credentials or Kochwiki access is required; see [frontend setup](../../README.md) for commands.

Submit arbitrary text to check the loading state and introduction, then both the `demo.greeting` artifact and the `demo.greetings` list of 30 greetings in the same turn, then a scripted error and completion guidance on the following message. The error's “Demo-Aktion (ohne Funktion)” button leaves the state unchanged. The demo host explicitly selects JSON presentation for both artifacts before the assistant reply. Check that the list starts collapsed and that “Mehr anzeigen” and “Weniger anzeigen” expand and collapse it. One more message triggers a frontend-only simulated 405 compatibility error without a retry action; the backend continues accepting messages. Refresh to restart with empty history; no dedicated restart button is provided. Generic error recovery actions remain available when failures occur. Also check that history scrolls without moving the page, the composer remains at the bottom through viewport-height changes, Enter and the send control submit once, Shift+Enter creates a line break, and long content causes no horizontal page scrolling.

## Advertising presentation capabilities

The UI entry point exports `ChatArtifactCapability` and
`JSON_ARTIFACT_CAPABILITY`, including the shared JSON renderer's usage description
and payload schema. Consumer frontends select the capabilities they support and
supply them beside caller context when creating a model-backed session:

```typescript
import { JSON_ARTIFACT_CAPABILITY } from '@roithme0/chat-ui/ui';

const input = {
  context: { selectedItem: item },
  artifactCapabilities: [JSON_ARTIFACT_CAPABILITY],
};
const transport = new HttpConversationTransport(
  '/ai/api/v1',
  AgentConfiguration.kochwiki,
  'kochwiki:42',
  input,
);
```

The AI Service supplies the agent with a local `present_artifact` tool. The agent
chooses when presentation helps and sends complete data; the renderer does not
fetch missing details. JSON presentation uses type `json` and payload
`{ value: <any JSON value> }`. With the default `presentArtifact` mapper, a backend
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
