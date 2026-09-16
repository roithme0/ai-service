# Chat UI integration POC

`@roithme0/chat-ui` is a small Angular 22 library. It renders a plain-text banner, places one optional static integration artifact, and invokes an Angular template supplied by the host. It makes no backend requests.

The public entry point exports `ChatUiComponent`, `ChatDemoRendererDirective`, `IntegrationDemoArtifact`, and `ChatDemoRendererContext`. The directive types `let-artifact` in the host template through Angular's context guard. Import the component and directive into the host component's `imports`.

```html
<ng-template aiChatDemoRenderer #preview="aiChatDemoRenderer" let-artifact>
  <h3>{{ artifact.payload.name }}</h3>
  <p>{{ artifact.payload.description }}</p>
</ng-template>
<ai-chat-ui
  bannerTitle="Integration demo"
  bannerDescription="Static content supplied by the host."
  [artifact]="demoArtifact"
  [renderer]="preview.template"
/>
```

The artifact has readonly fields `type: 'integration-demo'`, `id: string`, `headline: string`, and `payload: { name: string; description: string }`. It is a POC contract, not a recipe proposal. The renderer receives the artifact as `$implicit`. Without an artifact the UI contains only the banner. An artifact without a renderer displays a generic unavailable-preview message.

## Host theme

Set these CSS variables on an ancestor of `ai-chat-ui`:

| Property | Purpose | Default |
| --- | --- | --- |
| `--ai-chat-background` | Container background | `#fff8f8` |
| `--ai-chat-text` | General text and artifact headline | `#21191c` |
| `--ai-chat-banner-background` | Banner background | `#ffd9e1` |
| `--ai-chat-banner-text` | Banner text | `#3f001b` |

The component inherits typography. Styles are compiled into the library, so consumers need no separate stylesheet import. Defaults are `var()` fallback values and do not mask inherited host values. The library has no Kochwiki or Material dependencies.

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

This builds a partially compiled Angular package under `dist/chat-ui` and creates `dist/roithme0-chat-ui-0.0.0.tgz`. Angular common/core are peer dependencies rather than bundled runtimes. The package contains the public declarations, compiled component styles, and library JavaScript. The application remains independently buildable with `npm run build`.

From the common parent directory containing both repositories:

```powershell
New-Item -ItemType Directory -Force kochwiki-v2/frontend/vendor
Copy-Item -LiteralPath ai-service/frontend/dist/roithme0-chat-ui-0.0.0.tgz -Destination kochwiki-v2/frontend/vendor/
Set-Location kochwiki-v2/frontend
npm install ./vendor/roithme0-chat-ui-0.0.0.tgz
npm run build -- --configuration production --progress=false
npm test -- --watch=false --browsers=ChromeHeadlessNoSandbox --progress=false --include=src/app/chat-ui/pages/chat-ui-demo-page/chat-ui-demo-page.component.spec.ts
```

When migrating from the original package name, remove the old dependency and update imports to `@roithme0/chat-ui`. The installed dependency points to the copied tarball in Kochwiki's build context. Keep the tarball and updated manifest/lockfile together so `npm ci` and Docker builds do not require the AI Service checkout. Do not install using a source alias, symlink, force flag, or sibling source import.

Local builds always use the placeholder version. Rebuild and pack after changing the library:

```powershell
# In ai-service/frontend:
npm run pack:chat-ui
```

Rebuilding alone does not update the legacy Kochwiki tarball installation. Repeatedly installing a changed tarball with the same filename and version can reuse an old installed copy. Prefer the direct-link workflow after the registry migration.

## Browser verification

Start Kochwiki's normal local stack and frontend (see its deployment documentation), select a local user, then open `/chat-ui-demo` directly. The application header stays visible. The library owns banner/headline placement and renders Kochwiki's recipe template inside its artifact area.

Check a portrait phone viewport in both light and dark OS themes. In developer tools, change the integration ancestor's `--ai-chat-banner-background` and `--ai-chat-banner-text`: computed banner colors should change immediately. Disable the `.chat-ui-integration` mappings to verify readable library defaults. Automated integration checks also cover missing artifact/renderer and changing inherited variables.

The demo requires no AI model credentials. Kochwiki's existing user selection and application shell can still call its own backend; the chat library does not call AI Service.
