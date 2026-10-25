# AI Service

AI Service provides reusable AI capabilities to consuming applications, including conversations and a shared chat UI. This repository does not deliver a self-contained end-user product; included demos illustrate integration.

<img src="docs/assets/screenshots/ui-demo.jpg" alt="AI Service chat UI demo with messages, a JSON artifact, and the message composer" width="320">

## Features

- **Embeddings:** generate vectors through a stable profile, independently of conversations; consumers own storage and search.
- **Agent conversations:** run multi-turn conversations with live responses and tool progress.
- **Structured artifacts:** present agent results using JSON cards or your application's custom renderers.
- **Reusable chat UI:** embed the Angular chat component with optional session and connection handling.
- **Connected tools:** the Kochwiki agent combines model responses with domain tools supplied through MCP.
- **Scripted demo:** explore the UI, artifacts, and error states without model credentials.

## Documentation

See the [documentation overview](docs/README.md) for domain terminology, code navigation, development, operation, and architectural decisions.
