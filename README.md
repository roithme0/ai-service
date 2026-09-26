# AI Service

The AI Service provides shared, provider-neutral AI capabilities and an agent-based interface for projects in the network. It owns model integration, reusable AI operations, agent orchestration, and service connectors while domain services remain authoritative for their data and business rules.

The current implementation includes configured recipe-improvement and deterministic demo agent services, bounded model/tool orchestration, and a reusable chat UI library. This repository is authoritative for its implementation, API contracts, and deployment configuration. The application runs a deterministic UI demo, described in the [chat UI demo concept](docs/concepts/2026-09-25-chat-ui-demo.md).

## Core Features

- **Configured agent services**: A shared typed service hosts independent server-configured recipe and demo instances through one generic conversation HTTP API.
- **Supporting features**:
  - **Bounded AI capabilities**: Offer reusable operations requested by other services, initially including structured recipe optimization and, later, image generation.
  - **Conversation foundation**: Support ephemeral multi-turn recipe chat, multiple tool calls, explicit failures, and multiple proposal artifacts within one assistant turn. Responses are returned after turn completion; streaming and user-controlled cancellation are not implemented.
  - **Provider abstraction**: Keep model- and provider-specific behavior behind stable service interfaces.
  - **Generic tool orchestration**: Establish a constrained tool interface that can serve live-data tools and later project connectors without broad database, filesystem, or network access.
  - **Typed artifacts**: Validate recipe proposals at the service boundary and assign identifiers, ordering, timestamps, and validated base references in service code rather than through the model.
  - **Reusable chat UI**: Render host-supplied messages, artifacts, and status through a controlled Angular component with custom renderer support and a JSON fallback. The host owns session state and transport; the library makes no backend requests.

Domain services such as Kochwiki and Home Assistant continue to own their data, authorization, validation, persistence, and domain rules. They must remain useful when the AI Service is unavailable, and integrations use explicit APIs rather than direct access to their storage.

## Tech Stack

The frontend is an Angular 22 workspace containing the AI Service application and the independently packaged `@roithme0/chat-ui` library. The Python backend uses FastAPI and Pydantic, with an OpenAI Responses adapter behind a provider-neutral generation interface. Dockerfiles and Docker Compose configurations are provided for local development, testing, staging, and production.

Sessions retain their initialization snapshots, messages, and proposals in process-local memory with a fixed 90-minute lifetime. Clients submit messages and request turns against a session identifier; the backend supplies retained history to the model. There is no database-backed conversation storage, and sessions do not survive a backend restart. Durable history, listing, and resumption are outside the current scope. See the [backend README](backend/README.md) for setup and model/resolver configuration.

The checked-in `.codex/config.toml` enables Angular CLI and OpenAI documentation integrations for development.

## Workflows

The Angular application uses the shared conversation controller and HTTP transport with fixed `demo` configuration and empty input. Any submitted text advances the scripted sequence: greeting, real greeting-tool artifact rendered as JSON, then completion guidance. No AI model, OpenAI credentials, or Kochwiki access is needed. Refresh the page to restart with a new empty session. The recipe application and its fixture have been removed; the `kochwiki` backend configuration remains available for recipe integrations.

Run the complete application with `docker compose -f deployment/docker-compose-local.yml up --build` and open `http://localhost:8000` (or the configured gateway port). See [frontend setup](frontend/README.md) for separate development servers and [the library README](frontend/projects/chat-ui/README.md) for its public API and releases. Shared application modules remain internal; publication evaluation is deferred.

Use workflow skills only when explicitly invoked by the user.

- `$prepare-spec`: pressure-test a scoped change and create or refine its lightweight spec.
- `$deliver-spec`: plan and implement an approved spec continuously, pausing only for material exceptions.
- `$review-delivery`: perform the final spec-conformance, validation, and broader codebase review.
