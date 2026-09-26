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

Open `http://localhost:8000` (or the configured `GATEWAY_PORT`) for the scripted
chat UI demo. It requires no OpenAI credentials, model configuration, or reachable
Kochwiki service. Submit any text to advance through greeting, greeting-tool JSON
artifact, and completion. Refresh the page to restart with a new empty session.

Docker Compose reads `deployment/.env`. To enable recipe-improvement turns in
the container, add `OPENAI_API_KEY`, `RECIPE_IMPROVEMENT_OPENAI_MODEL`, and the
Kochwiki API base URL as `KOCHWIKI_BASE_URL`. That file is ignored by Git. The
variables are forwarded only to the backend. When Kochwiki runs directly on the
host, use `http://host.docker.internal:<port>/api`; `localhost` inside the backend
container refers to that container itself.

Run backend tests in a container:

```powershell
docker compose -f deployment/tests/backend/compose.yml up --build --abort-on-container-exit --exit-code-from backend-tests
```

The staging and production definitions deploy prebuilt backend and frontend images from Docker Hub. Staging uses the `alpha` tags and production uses the `latest` tags. The gateway is the only externally exposed application service; its port can be overridden with `GATEWAY_PORT`.

## Gateway timeouts

The `/api/` gateway uses a finite **600-second (10-minute) response read
timeout**, with 5-second upstream connection and request-send timeouts.
Upstream retries are disabled (`proxy_next_upstream off`) so state-changing
session/message/turn requests are not automatically replayed by the gateway.

Recipe turns return only after completion. The current backend allows eight
provider responses at 60 seconds each, with provider retries disabled, and six
tool attempts whose Kochwiki resolver has a 5-second timeout. The resulting
nominal budget is 510 seconds; 600 seconds leaves 90 seconds for orchestration
and transport overhead. These are operation limits, not a hard wall-clock turn
deadline. Nginx's [read timeout](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_read_timeout)
measures inactivity between upstream reads, not total request duration.

Kochwiki should use a proxy response timeout of at least 600 seconds when calling
the exposed AI Service gateway, preferably 660 seconds to let the gateway's
timeout response arrive first. Align any HTTP client total deadline accordingly,
keep connection timeouts short, and disable automatic retries of state-changing
requests. A timeout does not prove that a turn failed or was rolled back.

Run the isolated gateway regression test (no model credentials required):

```powershell
docker compose -f deployment/tests/gateway/compose.yml up --abort-on-container-exit --exit-code-from gateway-tests
docker compose -f deployment/tests/gateway/compose.yml down
```

It mounts the actual gateway configuration and checks POST turn responses delayed
65 seconds before any headers, preserving both HTTP 201 and HTTP 422 and their
exact JSON bodies. The two cases run concurrently and take about 65 seconds.
