# Repository navigation

AI Service runs agent conversations and provides a reusable Angular chat UI. This repository also includes a scripted demo application and a model-backed Kochwiki agent.

## System overview

```mermaid
flowchart LR
    Browser --> Gateway[NGINX gateway]
    Gateway -->|pages| Frontend[Angular demo app]
    Gateway -->|/api/ HTTP + SSE| Backend[FastAPI backend]
    Frontend --> ChatUI[Chat UI package]
    Consumer[External consumer frontend] --> ChatUI
    Consumer -->|HTTP + SSE| Backend
    Backend --> Engine[Pydantic AI]
    Engine --> OpenAI[OpenAI API]
    Engine -->|MCP| Kochwiki[External Kochwiki backend]
```

The [gateway](../deployment/gateway/nginx.conf) serves the demo and API. The demo uses a deterministic local model without external credentials; the Kochwiki agent uses OpenAI and external MCP tools. Sessions live in backend memory and do not survive restarts.

## Code map

| Area | Responsibilities and starting points |
| --- | --- |
| [Application](../backend/app/main.py) | FastAPI assembly and agent lifetimes. Registers the `demo` and `kochwiki` configurations; [settings](../backend/app/core/config.py) supply environment configuration. |
| [Session API](../backend/app/agentic/http.py) | Session creation, reads, prompt admission, and SSE observation under `/api/v1/agents/{configuration}/sessions`. [Presentation](../backend/app/agentic/presentation.py) projects native history into public snapshots. |
| [Execution](../backend/app/agentic/runner.py) | Owns background turns. [Registry](../backend/app/agentic/sessions.py) handles ownership and expiry; [session state](../backend/app/agentic/session_state.py) retains conversation, lifecycle, and artifacts. |
| [Agent composition](../backend/app/agentic/wiring.py) | Configures the Kochwiki model and MCP connection. [Turns](../backend/app/agentic/turns.py) execute through Pydantic AI; [artifacts](../backend/app/agentic/artifacts.py) validate and publish presentation data. |
| [Chat UI package](../frontend/projects/chat-ui/) | `@roithme0/chat-ui/ui` renders host-supplied content; `@roithme0/chat-ui/conversation` supplies the [controller](../frontend/projects/chat-ui/conversation/src/session-controller.ts), HTTP/SSE transport, and snapshot mapping. |
| [Demo app](../frontend/src/app/app.component.ts) | Hosts the chat UI and connects it to the [scripted backend agent](../backend/app/demo/agent.py). Includes simulated delays and error states. |
| [Deployment](../deployment/) | Environment-specific Compose definitions and gateway routing. The [publishing workflow](../.github/workflows/publish-app.yml) builds and publishes application images and the chat UI package. |

The [contract generator](../frontend/scripts/conversation-contract.mjs) produces [TypeScript types and Zod schemas](../frontend/projects/chat-ui/conversation/generated/) from the session router's OpenAPI document.

## Follow a flow

- **Send a prompt:** the controller calls the [transport](../frontend/projects/chat-ui/conversation/src/session-transport.ts) → session API → runner → session state → Pydantic AI. HTTP 202 acknowledges admission; execution continues in the background.
- **Display progress:** the runner streams complete snapshots over SSE → controller → [presentation mapper](../frontend/projects/chat-ui/conversation/src/session-presentation.ts) → [chat component](../frontend/projects/chat-ui/ui/lib/components/chat-ui/chat-ui.component.ts). Backend snapshots supply conversation content and execution status.
- **Present an artifact:** the consumer advertises supported schemas at session creation → the agent calls `present_artifact` → validation and session retention → snapshot → consumer renderer. Publication does not save domain data; domain operations belong to MCP tools.

## Find related tests

- Backend: [backend/tests/](../backend/tests/), covering session state, execution, HTTP/SSE, artifacts, agent wiring, and the demo.
- Frontend: `*.spec.ts` beside application and library code; tooling checks in [frontend/scripts/](../frontend/scripts/).
- Deployment: [deployment/tests/](../deployment/tests/), with backend and gateway test runners.
