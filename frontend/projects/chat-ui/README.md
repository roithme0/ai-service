# Chat UI integration POC

`@ai-service/chat-ui` is a small Angular 22 library. It renders a plain-text banner, places one optional static integration artifact, and invokes an Angular template supplied by the host. It makes no backend requests.

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

## Local tarball handoff

From `ai-service/frontend`:

```powershell
npm ci
npm run pack:chat-ui
```

This builds a partially compiled Angular package under `dist/chat-ui` and creates `dist/ai-service-chat-ui-0.0.1.tgz`. Angular common/core are peer dependencies rather than bundled runtimes. The package contains the public declarations, compiled component styles, and library JavaScript. The application remains independently buildable with `npm run build`.

From the common parent directory containing both repositories:

```powershell
New-Item -ItemType Directory -Force kochwiki-v2/frontend/vendor
Copy-Item -LiteralPath ai-service/frontend/dist/ai-service-chat-ui-0.0.1.tgz -Destination kochwiki-v2/frontend/vendor/
Set-Location kochwiki-v2/frontend
npm install ./vendor/ai-service-chat-ui-0.0.1.tgz
npm run build -- --configuration production --progress=false
npm test -- --watch=false --browsers=ChromeHeadlessNoSandbox --progress=false --include=src/app/chat-ui/pages/chat-ui-demo-page/chat-ui-demo-page.component.spec.ts
```

The installed dependency points to the copied tarball in Kochwiki's build context. Keep the tarball and updated manifest/lockfile together so `npm ci` and Docker builds do not require the AI Service checkout. Do not install using a source alias, symlink, force flag, or sibling source import.

For each subsequent change, bump the library version first, rebuild and pack, copy the new versioned tarball, and reinstall it:

```powershell
# In ai-service/frontend:
npm version patch --prefix projects/chat-ui --no-git-tag-version
npm run pack:chat-ui
```

Repeat the copy/install commands with the new tarball filename, then rerun the checks. A version bump and new tarball avoid npm reusing the old artifact. Rebuilding alone does not update Kochwiki. Registry publication and automatic rebuilds are deferred.

## Browser verification

Start Kochwiki's normal local stack and frontend (see its deployment documentation), select a local user, then open `/chat-ui-demo` directly. The application header stays visible. The library owns banner/headline placement and renders Kochwiki's recipe template inside its artifact area.

Check a portrait phone viewport in both light and dark OS themes. In developer tools, change the integration ancestor's `--ai-chat-banner-background` and `--ai-chat-banner-text`: computed banner colors should change immediately. Disable the `.chat-ui-integration` mappings to verify readable library defaults. Automated integration checks also cover missing artifact/renderer and changing inherited variables.

The demo requires no AI model credentials. Kochwiki's existing user selection and application shell can still call its own backend; the chat library does not call AI Service.
