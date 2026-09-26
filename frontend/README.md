# AI Service Frontend

The Angular application hosts a scripted chat UI demo using the real backend's `demo` configuration with empty initialization input. It imports the rendering component from `@roithme0/chat-ui/ui` and the controller and HTTP transport from `@roithme0/chat-ui/conversation`, using the default generic JSON mapper.

## Development server

From `backend`, run `python -m uvicorn app.main:app --port 8004`. From `frontend`, run:

```powershell
npm ci
npm run start:app
```

Open `http://localhost:4204`. The existing development proxy forwards `/api` to `http://localhost:8004`. No OpenAI credentials, model configuration, or reachable Kochwiki service is required for the demo. For the container setup, see [deployment](../deployment/README.md).

Every submitted message advances a fixed sequence regardless of its text: a brief loading state and scripted greeting, a real `demo.greeting` tool artifact with `{"message":"Hello, World!"}` displayed through the library's JSON fallback, then completion guidance. Further messages remain accepted. Refresh the page to create a new empty session and restart; there is no dedicated restart control. Generic error recovery actions remain available. Abandoned sessions expire in backend memory.

The recipe application, its fixture, and its presentation mapper have been removed. The backend's `kochwiki` configuration remains supported; its model and resolver setup is documented in [backend setup](../backend/README.md).

## Building

```powershell
npm run build:app
npm run build:chat-ui
```

## Running unit tests

```powershell
npm run test:app
npm run test:chat-ui
```

The `/ui` entry point owns chat rendering and accepts host-supplied content and status without network requests. The optional `/conversation` entry point provides the AI Service controller and HTTP transport. See [the library README](projects/chat-ui/README.md) for its API, themes, and local linking.
