# AI Service

The AI Service provides shared, provider-neutral AI capabilities and an agent-based interface for projects in the network. It owns model integration, reusable AI operations, agent orchestration, and service connectors while domain services remain authoritative for their data and business rules.

The project is currently at the initial setup stage. High-level product and architecture direction is maintained in the neighboring `plan` repository; this repository will become authoritative for its concrete implementation, API contracts, and deployment details as they are introduced.

## Core Features

- **Universal agent**: Provide an agent that can answer general questions, retrieve changing information through explicit tools, and progressively interact with authorized project APIs. Integrations begin read-only; mutations require deliberately scoped authorization, confirmation, validation, and auditing.
- **Supporting features**:
  - **Bounded AI capabilities**: Offer reusable operations requested by other services, initially including structured recipe optimization and, later, image generation.
  - **Conversation foundation**: Support ephemeral multi-turn chat, streaming, cancellation, multiple tool calls, explicit failures, and multiple typed artifacts within one assistant turn.
  - **Provider abstraction**: Keep model- and provider-specific behavior behind stable service interfaces.
  - **Generic tool orchestration**: Establish a constrained tool interface that can serve live-data tools and later project connectors without broad database, filesystem, or network access.
  - **Typed artifacts**: Validate versioned structured outputs at the service boundary and generate identifiers, ordering, timestamps, and references deterministically in service code rather than through the model.
  - **Reusable chat UI direction**: Explore a shared chat foundation that owns generic conversation behavior and allows host applications to supply renderers and bounded actions for domain-specific artifacts.

Domain services such as Kochwiki and Home Assistant continue to own their data, authorization, validation, persistence, and domain rules. They must remain useful when the AI Service is unavailable, and integrations use explicit APIs rather than direct access to their storage.

## Tech Stack

The implementation stack has not been selected yet. Do not infer a backend framework, frontend packaging model, database, model provider, or deployment mode from the project direction alone.

The intended first implementation is a provider-neutral model adapter and a generic, ephemeral, multi-turn chat. It should remain stateless where practical by accepting the relevant active conversation history from the client. Conversation persistence, listing, and resumption are not initial requirements.

The checked-in `.codex/config.toml` currently comes from the repository setup template. Its Angular CLI and OpenAI documentation integrations are starter configuration, not evidence of final application technology choices, and should be reviewed once the stack is selected.

## Workflows

Use workflow skills only when explicitly invoked by the user.

- `$prepare-spec`: pressure-test a scoped change and create or refine its lightweight spec.
- `$deliver-spec`: plan and implement an approved spec continuously, pausing only for material exceptions.
- `$review-delivery`: perform the final spec-conformance, validation, and broader codebase review.
