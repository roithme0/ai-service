# Operation

## Deployment layout

| Environment | Compose file | Image channel | Default gateway port |
| --- | --- | --- | --- |
| Local | [docker-compose-local.yml](../deployment/docker-compose-local.yml) | Built from source | 8004 |
| Staging | [docker-compose-staging.yml](../deployment/docker-compose-staging.yml) | `alpha` | 8004 |
| Production | [docker-compose-production.yml](../deployment/docker-compose-production.yml) | `latest` | 8005 |

The gateway exposes HTTP; backend and frontend stay on the Compose network. `GATEWAY_PORT` overrides the port. Retain [gateway/nginx.conf](../deployment/gateway/nginx.conf) beside the Compose files. Local and staging ports conflict unless overridden.

## Configuration

Create `deployment/.env` from [.env.example](../deployment/.env.example); host-side development uses `backend/.env`. Process environment values override backend file settings.

| Variable | Purpose |
| --- | --- |
| `GATEWAY_PORT` | Published gateway port for Compose. The example selects 8004. |
| `OPENAI_API_KEY` | Provider credentials for embeddings, Kochwiki, and Live Demo. |
| `KOCHWIKI_OPENAI_MODEL` | Model used by the Kochwiki agent. |
| `KOCHWIKI_MCP_URL` | External Streamable HTTP MCP endpoint, including its path. |
| `KOCHWIKI_OPENAI_REASONING_EFFORT` | Optional model reasoning effort; blank uses the model default. Support depends on the selected model. |

Visual Demo (`visual-demo`) needs no provider or Kochwiki settings. Live Demo (`live-demo`) requires only `OPENAI_API_KEY`; Kochwiki also requires its model and MCP URL. Missing required settings or initialization failure leaves the affected agent unavailable with `503 agent_unavailable`; restart after correcting startup configuration. Kochwiki connects MCP per turn, so an outage can recover on a later turn without restarting.

For a Kochwiki server on the Docker host, the example uses `http://host.docker.internal:8002/mcp/`; ensure that name resolves on your host. Container `localhost` refers to the container itself.

The API uses the caller-supplied `X-Application-User` header (`encodeURIComponent(issuer):encodeURIComponent(subject)`) for session ownership and forwards the session owner's assertion to Kochwiki MCP on every turn. Both boundaries temporarily accept unverified assertions; authenticated delegation remains future work. Configure HTTPS at the hosting edge.

## Deploy or update

From **deployment/**, for production; substitute the staging filename as needed:

```powershell
docker compose --env-file .env -f docker-compose-production.yml pull
docker compose --env-file .env -f docker-compose-production.yml up -d
docker compose --env-file .env -f docker-compose-production.yml ps -a
docker compose --env-file .env -f docker-compose-production.yml logs --tail=100 backend gateway
```

Check the visual demo through the gateway by submitting messages and observing text, artifacts, and the intentional scripted failure. Test Kochwiki through a configured consumer if enabled. Container startup alone does not verify model or MCP connectivity.

### Releases

The [publishing workflow](../.github/workflows/publish-app.yml) publishes both Docker Hub images and `@roithme0/chat-ui` to GitHub Packages from one commit. It does not deploy to a host.

| Repository tag | Published version | Channel |
| --- | --- | --- |
| `v1.2.0` | `1.2.0` | `latest` |
| `v1.3.0-alpha.1` | `1.3.0-alpha.1` | `alpha` |

Tags allow three numeric version parts, optionally `-alpha` or `-alpha.N`, without leading zeroes. Each release needs a new version; source package versions remain unchanged. Both builds must succeed before publication, but registry failures can still leave a partial release. Verify the entire workflow succeeded.

Record image IDs before updating. Channel tags move; matching version tags or digests make rollback reproducible. Recreating the backend loses active sessions.

## Persistence and recovery

There is no database, persistent session volume, or conversation restore workflow. Sessions, history, and accepted artifacts live in one backend process and disappear on restart. Multiple workers or replicas do not share them.

Retain deployment configuration and protect backups of credentials. Application rollback can restore image versions but cannot restore conversations. Data changed through MCP belongs to the external service and its backup procedures.

## Troubleshooting

| Symptom | Start here |
| --- | --- |
| An agent returns 503 | Backend initialization logs and the [required configuration](#configuration). |
| A turn fails | Backend logs, model access, and MCP reachability from the backend. Interrupted external operations may already have taken effect. |
| Embedding generation fails | `OPENAI_API_KEY`, provider reachability, and embedding logs. |
| Session returns 404 | Agent configuration, owner header, fixed session expiry, or backend restart. See [session rules](domains/conversations.md#session-rules). |
| Submission returns 409 | A turn is already running, or the conversation budget is exhausted. |
| Observation disconnects | Gateway/upstream connectivity. The controller reconnects transient failures; this does not resubmit prompts. |

The [gateway](../deployment/gateway/nginx.conf) has a 600-second read inactivity timeout and no upstream retries. SSE has no heartbeat, so idle connections can time out. A lost admission response does not establish whether execution started; do not blindly replay it. Execution budgets live in [conversations/config.py](../backend/app/capabilities/conversations/config.py).
