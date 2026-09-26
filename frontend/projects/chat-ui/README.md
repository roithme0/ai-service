# Chat UI

`@roithme0/chat-ui` is a controlled Angular 22 conversation component. It renders ordered host-supplied text and JSON-compatible artifacts, emits normalized user submissions and generic status actions, and leaves conversation state and transport orchestration to the host. It makes no backend requests.

The public entry point exports `ChatUiComponent` and the typed content, artifact renderer, submission, status, and status-action contracts. Import the component into the host component's `imports`.

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

Text content has readonly `kind`, `id`, `role` (`user` or `assistant`), and `text` fields. Artifacts have readonly `kind`, `id`, `type`, `headline`, and recursive `JsonValue` payload fields. Identity is host-supplied and should remain stable when the collection changes. User text is always rendered literally. Assistant text supports a constrained Markdown subset: headings, paragraphs, emphasis, strong text, inline and fenced code, ordered and unordered lists, blockquotes, and safe HTTP(S), mail, root-relative, or fragment links. Raw HTML and unsafe link schemes are not interpreted.

Map artifact type discriminators to typed Angular templates with `artifactRenderer(template)`. An absent mapping uses the built-in escaped, formatted JSON view. The library frames every artifact and clips renderer bodies above `--ai-chat-artifact-collapsed-height` (default `18rem`) with German expand/collapse controls and no nested scrolling area.

The component trims a valid submission and emits it once as a `ChatSubmission`. It retains the draft until the host calls `acknowledge`, so the visible composer can remain truthful to backend acceptance. It never adds that text to `content`; the host updates or replaces its own collection in response. Enter submits, while Shift+Enter adds a line break.

`conversationStatus` accepts a host-controlled loading or error state, its placement, and an optional generic action. `composerDisabled` blocks concurrent submissions. Status actions emit their opaque ID to the host; neither contract contains backend- or recipe-specific types.

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
| `--ai-chat-artifact-heading`      | Artifact headline              | `#f8eef1`    |
| `--ai-chat-artifact-text`         | JSON fallback text             | `#eadde2`    |
| `--ai-chat-composer-background`   | Composer field background      | `#291c21`    |
| `--ai-chat-composer-border`       | Composer field border          | `#50363f`    |
| `--ai-chat-composer-text`         | Composer field text            | `#f8eef1`    |
| `--ai-chat-send-background`       | Send control background        | `#c00059`    |
| `--ai-chat-send-hover-background` | Send control hover background  | `#df0067`    |
| `--ai-chat-send-text`             | Send control foreground        | `#ffffff`    |
| `--ai-chat-focus`                 | Keyboard focus ring            | `#ff9fc1`    |

The component inherits typography. Its chat-specific styles are compiled into the library, while the host-provided Angular Material theme styles its Material controls. CSS variable defaults are `var()` fallback values and do not mask inherited host values. The library has no Kochwiki dependency.

## GitHub Packages releases

The library publishes to `https://npm.pkg.github.com` and is associated with `roithme0/ai-service`. The `Build and publish chat UI package` workflow builds the library on pull requests and pushed `chat-ui-v*` tags, uploading the built package as a workflow artifact. A separate publish job runs only for release tags and downloads that same artifact. Only the publish job receives `packages: write` permission.

The tag determines the published version: `chat-ui-v0.0.2` publishes `0.0.2`. Tags must use three numeric version parts without leading zeroes; prerelease tags are not supported yet. The publish job sets the version in `dist/chat-ui/package.json` and publishes using its `GITHUB_TOKEN`. The source package keeps the local placeholder version `0.0.0` and is not modified by the workflow.

For the first registry release, commit the library and workflow changes, then tag that commit and push the tag:

```powershell
git tag chat-ui-v0.0.2
git push origin chat-ui-v0.0.2
```

For later releases, commit the library changes and push a new version tag from the repository root. No package version edit is required:

```powershell
git tag chat-ui-v0.0.3
git push origin chat-ui-v0.0.3
```

Each release needs a new version. Kochwiki has read access under the package's **Manage Actions access** settings and consumes the package from GitHub Packages. Its CI passes the repository's short-lived `GITHUB_TOKEN` to Docker as a BuildKit secret.

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

When migrating from the original package name or the artifact-renderer POC, remove the old dependency, update imports to `@roithme0/chat-ui`, and adapt the host to the controlled `messages` input and `messageSubmitted` output before running its build. Run the consumer's focused tests for its current chat host after that migration; they should cover message projection and submission orchestration rather than the removed POC renderer. This library does not prescribe a consumer test-file path.

The installed dependency points to the copied tarball in Kochwiki's build context. Keep the tarball and updated manifest/lockfile together so `npm ci` and Docker builds do not require the AI Service checkout. Do not install using a source alias, symlink, force flag, or sibling source import.

Local builds always use the placeholder version. Rebuild and pack after changing the library:

```powershell
# In ai-service/frontend:
npm run pack:chat-ui
```

Rebuilding alone does not update the legacy Kochwiki tarball installation. Repeatedly installing a changed tarball with the same filename and version can reuse an old installed copy. Prefer the direct-link workflow after the registry migration.

## Browser verification

Run the backend on port 8004 and `npm run start:app` in `frontend`, then open `http://localhost:4204` at a portrait-phone viewport. The host creates an empty `demo` session and advances a scripted sequence through the real backend. No model credentials or Kochwiki access is required; see [frontend setup](../../README.md) for commands.

Submit arbitrary text to check the brief loading state and greeting, then the `demo.greeting` artifact through JSON fallback before the assistant reply, then completion guidance. Further submissions remain enabled. Refresh to restart with empty history; no dedicated restart button is provided. Generic error recovery actions remain available when failures occur. Also check that history scrolls without moving the page, the composer remains at the bottom through viewport-height changes, Enter and the send control submit once, Shift+Enter creates a line break, and long content causes no horizontal page scrolling.
