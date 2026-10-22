# AI Service

The AI Service is a personal project that provides shared, provider-neutral AI capabilities and an agent-based interface for related projects. It owns model integration, reusable AI operations, agent orchestration, and service connectors while domain services remain authoritative for their data and business rules.

The current implementation includes configured KochWiki and deterministic demo agent services, bounded model/tool orchestration, and a reusable chat UI library. This repository is authoritative for its implementation, API contracts, and deployment configuration. The application runs a deterministic UI demo.

## Core Features

- **Configured agent services**: Kochwiki and the demo use the Pydantic AI session API. Kochwiki configuration or MCP failures do not prevent the application from starting.
- **Supporting features**:
  - **Bounded AI capabilities**: Offer reusable operations requested by other services, including MCP-backed recipe conversations.
  - **Conversation foundation**: Support ephemeral multi-turn chat, multiple tool calls, explicit failures, and artifact acceptance and ordered turn-owned UI timelines of messages, tool activity and embedded artifacts. Model-backed sessions can publish explicit artifacts using caller-advertised presentation capabilities; the demo also exercises artifact publishing. Complete messages, requested/running/outcome tool rows, and accepted artifacts stream live through backend-owned turns and a separate SSE observer. The session controller reconnects observation after transient failures and restores state from a fresh snapshot; submission remains disabled until observation recovers. Lost submission acknowledgements remain uncertain. Refresh recovery and user-controlled cancellation are not implemented.
  - **Provider abstraction**: Keep model- and provider-specific behavior behind stable service interfaces.
  - **Generic tool orchestration**: Establish a constrained tool interface that can serve live-data tools and later project connectors without broad database, filesystem, or network access.
  - **Typed artifacts**: Assign shared artifact identity, ordering and timestamps in service code. The demo and model-backed presentations use this foundation; Kochwiki proposals and drafts remain owned by its MCP server.
  - **Reusable chat UI**: The `/ui` entry point renders host-supplied messages, artifacts, and status through a controlled Angular component with custom renderer support and an explicit JSON renderer, without making backend requests. The optional `/conversation` entry point provides conversation control and HTTP transport for the AI Service API; the host configures the integration and binds its view state.

Domain services such as Kochwiki and Home Assistant continue to own their data, authorization, validation, persistence, and domain rules. They must remain useful when the AI Service is unavailable, and integrations use explicit APIs rather than direct access to their storage.

## Tech Stack

The frontend is an Angular 22 workspace containing the AI Service application and the independently packaged `@roithme0/chat-ui` library. The Python backend uses FastAPI, Pydantic and Pydantic AI. Pydantic AI owns execution, tools and history for both agent configurations. Dockerfiles and Docker Compose configurations are provided for local development, testing, staging, and production.

Sessions retain their initialization snapshots, messages, and any published artifacts in process-local memory with a fixed 90-minute lifetime. Clients submit prompts against a session identifier and observe complete session snapshots through the Pydantic AI session API. The engine retains a native Pydantic AI `Conversation` for continuation, including cumulative usage. Per-turn budgets remain separate from the conversation-wide cap of 50 model requests and 40 successful tool calls; exhaustion disables submission while keeping history readable. There is no database-backed conversation storage, and sessions do not survive a backend restart. Durable history, listing, and resumption are outside the current scope. See the [backend README](backend/README.md) for setup and model/MCP configuration.

Frontend formatting, linting, tests, and Codex hook behavior are documented in [frontend validation](docs/frontend-validation.md). The Stop hook formats changed frontend files, checks whole-frontend lint, and runs tooling tests plus both Angular test suites. CI runs read-only linting.

The checked-in `.codex/config.toml` enables Angular CLI and OpenAI documentation integrations for development.

## Workflows

The Angular demo uses `SessionController` and the HTTP transport with fixed `demo` configuration, the advertised built-in JSON artifact capability, and application identity `demo:default`. Its session requests use `/api/v1/agents/demo/sessions`. A deterministic Pydantic AI `FunctionModel` drives the shared agent runner, session lifecycle and `present_artifact` tool. Kochwiki uses the same session contract at `/api/v1/agents/kochwiki/sessions`. All conversation requests, including SSE observation, require the `X-Application-User` header; the transport sends its explicit host-supplied identity. This trusted-LAN identity is format-validated but not authenticated, and each session has a fixed owner. Reads, prompt submission, and SSE observation require that same identity; another owner receives the existing not-found response. Any submitted text advances the scripted sequence: introduction, two greeting artifacts from the same turn (including a list of 30 greetings that exercises artifact collapse and expansion), one scripted error, then completion guidance. A further message triggers a frontend-only simulated 405 compatibility error. Both artifacts are validated and published by the `present_artifact` tool and rendered as JSON. No AI model, OpenAI credentials, or Kochwiki access is needed. Refresh the page to restart with a new empty session.

Run the complete application with `docker compose -f deployment/docker-compose-local.yml up --build` and open `http://localhost:8000` (or the configured gateway port). See [frontend setup](frontend/README.md) for separate development servers and [the library README](frontend/projects/chat-ui/README.md) for its public API and releases. The package exposes `/ui` for rendering and `/conversation` for AI Service integration.

Use workflow skills only when explicitly invoked by the user.

Implementation-specific concepts, plans, and specs live in `.agents/concepts/`, `.agents/plans/`, and `.agents/specs/`. These temporary files are gitignored and remain available through final review; cleanup is manual. Permanent documentation must never reference or depend on them.

- `$prepare-spec`: pressure-test a scoped change and create or refine its lightweight spec.
- `$deliver-spec`: plan and implement an approved spec continuously, pausing only for material exceptions.
- `$review-delivery`: perform the final spec-conformance, validation, and broader codebase review.
