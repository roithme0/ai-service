# Chat UI

`@roithme0/chat-ui` is one Angular 22 package with two public entry points. `@roithme0/chat-ui/ui` provides the controlled conversation component; `@roithme0/chat-ui/conversation` optionally provides the AI Service conversation controller and HTTP transport. The UI entry point renders ordered host-supplied text and JSON-compatible artifacts, emits normalized user submissions and generic status actions, and leaves conversation state and transport orchestration to the host. It makes no backend requests.

The `/ui` entry point exports `ChatUiComponent` and the typed content, artifact renderer, submission, status, and status-action contracts. Import the component into the host component's `imports`.

```html
<ai-chat-ui
  bannerTitle="Rezept gemeinsam verbessern"
  bannerDescription="Beschreibe, was du ändern möchtest."
  [content]="content()"
  [artifactRenderers]="artifactRenderers"
  [composerDisabled]="pending()"
  [conversationStatus]="status()"
  (messageSubmitted)="handleMessage($event)"
  (statusActionTriggered)="handleStatusAction($event)"
/>
```

Text content has readonly `kind`, `id`, `role` (`user` or `assistant`), and `text` fields. Artifacts have readonly `kind`, `id`, `type`, `headline`, optional `subtitle`, and recursive `JsonValue` payload fields. Identity is host-supplied and should remain stable when the collection changes. User text is always rendered literally. Assistant text supports a constrained Markdown subset: headings, paragraphs, emphasis, strong text, inline and fenced code, ordered and unordered lists, blockquotes, and safe HTTP(S), mail, root-relative, or fragment links. Raw HTML and unsafe link schemes are not interpreted.

Map artifact type discriminators to typed Angular templates with `artifactRenderer(template)`. The built-in `json` type renders the escaped, formatted `payload.value`. An absent mapping for any other type shows an unsupported-presentation message; it does not silently select JSON. The library frames every artifact and clips renderer bodies above `--ai-chat-artifact-collapsed-height` (default `18rem`) with German expand/collapse controls and no nested scrolling area.

The component trims a valid submission and emits it once as a `ChatSubmission`. It retains the draft until the host calls `acknowledge`, so the visible composer can remain truthful to backend acceptance. It never adds that text to `content`; the host updates or replaces its own collection in response. Enter submits, while Shift+Enter adds a line break. New content and status changes smoothly scroll the conversation history to the bottom, including when a delayed status becomes visible, even if the user had scrolled up.

`conversationStatus` accepts a host-controlled loading or error state, its placement, and an optional generic action. All loading labels fade in over 180 ms, including initialization and response generation. Loading states can opt into `reveal: 'delayed'`: the UI reserves a line and waits 300 ms before starting the fade. Replacing the status cancels the pending reveal. The conversation controller uses this delay for sending messages. Errors appear immediately without animation. Changing the status label restarts its fade. Fades also run when reduced motion is preferred. `composerDisabled` blocks concurrent submissions. Set `focusOnReady` to focus the composer once when it first becomes enabled, provided focus has not moved to another control in the meantime. Status actions emit their opaque ID to the host; neither contract contains backend- or recipe-specific types.

## AI Service conversation integration

The root entry point exports no API. This is a breaking import migration: replace root imports with `@roithme0/chat-ui/ui`. Import conversation support from `@roithme0/chat-ui/conversation`. Upgrade consumer imports together with the package; there are no compatibility re-exports. Both entry points share the existing package version and release lifecycle.

A complete minimal standalone host (with the Material theme described below):

```typescript
import { Component, OnInit, signal } from '@angular/core';
import { ChatUiComponent, type ChatSubmission } from '@roithme0/chat-ui/ui';
import {
  AgentConfiguration, ConversationController, HttpConversationTransport, presentJsonArtifact,
  type ConversationViewState,
} from '@roithme0/chat-ui/conversation';

@Component({
  selector: 'app-chat',
  imports: [ChatUiComponent],
  template: `
    <ai-chat-ui
      bannerTitle="Chat demo"
      bannerDescription="Any text advances the scripted sequence."
      [content]="chat().content"
      [composerDisabled]="chat().composerDisabled"
      [conversationStatus]="chat().status"
      (messageSubmitted)="submit($event)"
      (statusActionTriggered)="act($event)"
    />`,
})
export class ChatHost implements OnInit {
  readonly chat = signal<ConversationViewState>({
    content: [], composerDisabled: true, status: null,
  });
  private readonly controller = new ConversationController(
    new HttpConversationTransport('/api/v1', AgentConfiguration.demo),
    (state) => this.chat.set(state),
    presentJsonArtifact,
  );

  ngOnInit(): void { void this.controller.start(); }
  submit(value: ChatSubmission): void {
    void this.controller.submit(value.text, value.acknowledge);
  }
  act(id: string): void { void this.controller.performAction(id); }
}
```

The required base URL is the prefix immediately before `/agents`: `/api/v1` yields `/api/v1/agents/demo/sessions`; `/ai/api/v1/` yields `/ai/api/v1/agents/demo/sessions`. Trailing joining slashes are normalized; another `/api/v1` is never appended. Absolute URLs use the same joining behavior. Normal deployment uses a same-origin relative prefix.

`AgentConfiguration` exports the backend-derived `demo` and `kochwiki` values, plus the derived union type of the same name. Arbitrary string keys are rejected by the TypeScript contract. Known keys do not guarantee runtime availability; the server can return `agent_unavailable`.

The transport binds the URL, agent key, and optional third constructor argument for initialization input. Omitted input sends `{ input: {} }`; supplied input uses `{ input: suppliedInput }`. Replacement sessions use the same transport settings. Server validation is authoritative, and configurations requiring domain input can reject an empty input. No recipe types or fixtures are packaged.

The controller's optional third constructor argument is an `ArtifactMapper`. It receives the full `ArtifactResponse` envelope and returns a `ChatArtifact` or `null` to omit it. `presentArtifact` is the default mapper: it preserves the advertised type and identity and unwraps the backend presentation payload `{ title, payload }`. `presentJsonArtifact` is an explicit adapter for hosts such as the deterministic demo that deliberately present arbitrary tool payloads using type `json` and `{ value: originalPayload }`; the controller sorts artifacts by backend order and associates history artifacts with their turns. The host owns view-state binding, introductory text and custom renderer registration.

The supported HTTP contract is this repository's AI Service conversation API. `ConversationTransport` remains available for isolated tests. The controller retains acceptance acknowledgement, ambiguous-request reconciliation, turn execution, failure classification and existing recovery actions. It adds no polling, automatic retries, persistence, streaming or cancellation.

Expected routing is host frontend ? same-origin backend/proxy ? AI Service gateway. Relays must preserve response bodies and status codes, allow agent-turn durations, and avoid automatic retries of state-changing message/turn requests. Consumer relay implementation and authentication/session authorization are deferred. Same-origin routing is not an authorization guarantee.

## Built-package verification

From `frontend`, run `npm run build:chat-ui`, then `node scripts/check-chat-ui-package.mjs`. This checks actual package exports and declarations with ordinary package resolution, exercises the built conversation module, rejects arbitrary configuration keys and checks that the root exports no API. Workspace source aliases are not used.

## Host theme

The host must install compatible Angular Material and CDK versions and provide an Angular Material theme. For example, a host can import a prebuilt theme in its global stylesheet:

```css
@import '@angular/material/prebuilt-themes/magenta-violet.css';
```

The library packages selected SVGs from Google's Material Icons collection and registers `send`, `retry`, `tts`, and `add-file` in the `ai-chat` namespace. Its controls reference them through names such as `ai-chat:send`. Hosts do not need to load the Material Icons font or register these icons. The source icons and their Apache 2.0 terms are documented in `MATERIAL_ICONS_LICENSE` in the published package.

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
| `--ai-chat-artifact-text`         | JSON presentation text             | `#eadde2`    |
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
const transport = new HttpConversationTransport('/ai/api/v1', AgentConfiguration.kochwiki, input);
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
