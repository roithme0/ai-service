# AI Service Frontend

The Angular application hosts a scripted chat UI demo using the backend's `demo` configuration at `/api/native/api/v1/agents/demo/sessions`. It imports the rendering component from `@roithme0/chat-ui/ui` and `SessionController` with `HttpSessionTransport` from `@roithme0/chat-ui/conversation`. Initialization advertises `JSON_ARTIFACT_CAPABILITY`; the default artifact mapper passes its `{ value: <JSON value> }` payloads directly to JSON cards. A local Pydantic AI `FunctionModel` supplies deterministic responses without an external model. Displayed history comes only from complete backend snapshots; HTTP admission clears the draft without inserting an optimistic prompt.

## Development server

From `backend`, run `python -m uvicorn app.main:app --port 8004`. From `frontend`, run:

```powershell
npm ci
npm run start:app
```

Open `http://localhost:4204`. The existing development proxy forwards `/api` to `http://localhost:8004`. No OpenAI credentials, model configuration, or reachable Kochwiki service is required for the demo. For the container setup, see [deployment](../deployment/README.md).

Every submitted message advances a fixed sequence regardless of its text: a loading state and scripted introduction, a turn creating both a JSON artifact titled `demo.greeting` with `{"message":"Hello, World!"}` and a JSON artifact titled `demo.greetings` containing 30 greetings, a deliberately invalid artifact publication, one scripted turn error with a labeled no-op action, then completion guidance. `present_artifact` calls appear as secondary-color rows with a shared tool icon and live requested, running, and outcome statuses, interleaved with their artifacts. Artifacts retained from failed turns are also displayed. Both artifacts explicitly select the library's JSON renderer; the longer list demonstrates “Mehr anzeigen” and “Weniger anzeigen”. The next message triggers a frontend-only simulated 405 compatibility error and disables further submissions; the backend itself continues accepting messages. Refresh the page to create a new empty session and restart; there is no dedicated restart control. Transient observation loss disables sending while the controller reconnects after a one-second delay. The next backend snapshot restores the current state without resubmitting the prompt; a lost admission acknowledgement remains uncertain. Abandoned sessions expire in backend memory.

Kochwiki model and MCP configuration is documented in [backend setup](../backend/README.md).

## Building

```powershell
npm run build:app
npm run build:chat-ui
```

## Conversation contract

The Pydantic AI session router's OpenAPI document is the source for the conversation entry point's generated TypeScript types and Zod validators. Generation mounts that router in an isolated FastAPI app, matching the session boundary used by the demo. With the backend Python environment active, run `npm run generate:conversation-contract` from `frontend` after changing the API models, then commit the updated `projects/chat-ui/conversation/generated` files. Run `npm run check:conversation-contract` to compare them with the current backend document; the chat UI package and application image workflows run this check before publishing. Set `PYTHON` to the backend Python executable if it is not on the active path. The HTTP transport validates successful and failed response bodies with the generated schemas and checks outgoing request envelopes against generated types.

## Running unit tests

```powershell
npm run test:app
npm run test:chat-ui
```

The `/ui` entry point owns chat rendering and accepts host-supplied content and status without network requests. The optional `/conversation` entry point provides the AI Service controller and HTTP transport. See [the library README](projects/chat-ui/README.md) for its API, themes, and local linking.
