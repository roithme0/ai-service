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

The staging and production definitions deploy prebuilt backend and frontend images from Docker Hub. Staging uses the `alpha` tags and production uses the `latest` tags. The gateway is the only externally exposed application service; its port can be overridden with `GATEWAY_PORT`.
