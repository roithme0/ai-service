# Deployment

The deployment layout follows the same convention as Kochwiki: application images are defined beside the backend and frontend, while Compose files for each environment live here.

Run the local application from the repository root:

```powershell
docker compose -f deployment/docker-compose-local.yml up --build
```

Run backend tests in a container:

```powershell
docker compose -f deployment/docker-compose-test.yml up --build --abort-on-container-exit --exit-code-from backend-tests
```

The staging and production definitions deploy prebuilt backend and frontend images. Set `AI_SERVICE_BACKEND_IMAGE` and `AI_SERVICE_FRONTEND_IMAGE` to immutable image references before using them. The gateway is the only externally exposed application service; its port can be overridden with `FRONTEND_PORT`.
