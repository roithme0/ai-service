# AI Service Frontend

The Angular application hosts a scripted chat UI demo using the real backend's `demo` configuration with empty initialization input. It imports the rendering component from `@roithme0/chat-ui/ui` and the controller and HTTP transport from `@roithme0/chat-ui/conversation`, using the default generic JSON mapper.

## Development server

From `backend`, run `python -m uvicorn app.main:app --port 8004`. From `frontend`, run:

```powershell
npm ci
npm run start:app
```

Open `http://localhost:4204`. The existing development proxy forwards `/api` to `http://localhost:8004`. No OpenAI credentials, model configuration, or reachable Kochwiki service is required for the demo. For the container setup, see [deployment](../deployment/README.md).

Every submitted message advances a fixed sequence regardless of its text: a loading state and scripted introduction, a turn creating both a real `demo.greeting` artifact with `{"message":"Hello, World!"}` and a `demo.greetings` artifact containing 30 greetings, one scripted error with a labeled no-op action, then completion guidance. Both artifacts use the library's JSON fallback; the longer list demonstrates “Mehr anzeigen” and “Weniger anzeigen”. Further messages remain accepted. Refresh the page to create a new empty session and restart; there is no dedicated restart control. Generic error recovery actions remain available. Abandoned sessions expire in backend memory.

The recipe application, its fixture, and its presentation mapper have been removed. The backend's `kochwiki` configuration remains supported; its model and resolver setup is documented in [backend setup](../backend/README.md).

## Building

```powershell
npm run build:app
npm run build:chat-ui
```

## Conversation contract

The backend's FastAPI OpenAPI document is the source for the conversation entry point's generated TypeScript types and Zod validators. With the backend Python environment active, run `npm run generate:conversation-contract` from `frontend` after changing the API models, then commit the updated `projects/chat-ui/conversation/generated` files. Run `npm run check:conversation-contract` to compare them with the current backend document; the chat UI package and application image workflows run this check before publishing. Set `PYTHON` to the backend Python executable if it is not on the active path. The HTTP transport validates successful and failed response bodies with the generated schemas and checks outgoing request envelopes against generated types.

## Running unit tests

```powershell
npm run test:app
npm run test:chat-ui
```

The `/ui` entry point owns chat rendering and accepts host-supplied content and status without network requests. The optional `/conversation` entry point provides the AI Service controller and HTTP transport. See [the library README](projects/chat-ui/README.md) for its API, themes, and local linking.
