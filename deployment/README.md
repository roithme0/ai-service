# Deployment

The deployment layout follows the same convention as Kochwiki: application images are defined beside the backend and frontend, while Compose files for each environment live here.

The shared gateway configuration is `nginx.conf` in this directory.

Deployment test runners live in `tests/backend/` and `tests/gateway/`, each with
its own `compose.yml`. Backend Python tests remain in `backend/tests/` at the
repository root; the gateway test harness lives beside its test Compose file.

Run the local application from the repository root:

```powershell
docker compose -f deployment/docker-compose-local.yml up --build
```

Open `http://localhost:8004` (or the configured `GATEWAY_PORT`) for the scripted
chat UI demo. It requires no OpenAI credentials, model configuration, or reachable
Kochwiki service. Submit any text to advance through an introduction, two JSON artifacts, a scripted
turn failure, and completion guidance. Refresh the page to restart with a new empty session.

Docker Compose reads `deployment/.env`. To enable Kochwiki turns in the
container, add `OPENAI_API_KEY`, `KOCHWIKI_OPENAI_MODEL`, and `KOCHWIKI_MCP_URL`.
That file is ignored by Git. The variables are forwarded only to the backend.
Optionally set `KOCHWIKI_OPENAI_REASONING_EFFORT` alongside the model name;
all three Compose environments forward it to the backend. Blank or unset
keeps the model's default. See [backend configuration](../backend/README.md#local-development)
for accepted values and model-specific restrictions.
When Kochwiki runs directly on the host, use
`http://host.docker.internal:<port>/mcp/`; `localhost` inside the backend
container refers to that container itself.

Run backend tests in a container:

```powershell
docker compose -f deployment/tests/backend/compose.yml up --build --abort-on-container-exit --exit-code-from backend-tests
```

The staging and production definitions deploy prebuilt backend and frontend images from Docker Hub. Staging uses the `alpha` tags and gateway port 8004; production uses the `latest` tags and gateway port 8005. The gateway is the only externally exposed application service; its port can be overridden with `GATEWAY_PORT`.

Push a `v`-prefixed repository version tag to publish both application images and the chat UI package from the same commit through the `Build and publish app and chat UI` workflow. For example, `v1.2.0` publishes version `1.2.0` and updates `latest`; `v1.3.0-alpha.1` publishes version `1.3.0-alpha.1` and updates `alpha`. Every release publishes all components, including unchanged ones. The `build-app` job builds both images and exports OCI archives with provenance and SBOM metadata. Both `publish-app` and `publish-chat-ui` wait for the application and library builds to succeed, including the application build's contract checks and backend tests, before publishing the built artifacts. A failed build prevents all publication; a registry failure during publication can still leave a partial release. Verify the entire workflow succeeded before treating the release as complete. See the [library release instructions](../frontend/projects/chat-ui/README.md#github-packages-releases) for tag rules and commands.

## Gateway timeouts

The `/api/` gateway uses a finite **600-second (10-minute) response read
timeout**, with 5-second upstream connection and request-send timeouts.
Upstream retries are disabled (`proxy_next_upstream off`) so state-changing
session creation and prompt submissions are not automatically replayed by the gateway.

Prompt submission returns HTTP 202 after admission; execution continues in the
background. Clients observe complete session snapshots over SSE across turns.
The gateway read timeout measures inactivity between upstream reads, not total
turn duration. Observation has no heartbeat, so an idle connection can reach this
timeout; the session controller reconnects and receives a fresh snapshot.

Execution budgets are configured in `backend/app/agentic/config.py`; they are
independent of the gateway timeout. Keep automatic retries disabled for
state-changing requests. A lost admission response or connection timeout does
not prove that execution failed or was rolled back.

Run the isolated gateway regression test (no model credentials required):

```powershell
docker compose -f deployment/tests/gateway/compose.yml up --abort-on-container-exit --exit-code-from gateway-tests
docker compose -f deployment/tests/gateway/compose.yml down
```

It mounts the actual gateway configuration and checks synthetic POST responses delayed
65 seconds before any headers, preserving both HTTP 201 and HTTP 422 and their
exact JSON bodies. The two cases run concurrently and take about 65 seconds.
