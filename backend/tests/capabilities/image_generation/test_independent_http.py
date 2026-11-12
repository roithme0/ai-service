import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import httpx
from pydantic_ai.images import ImageGenerator

from app.capabilities.image_generation.service import (
    PNG_SIGNATURE,
    ImageGenerationService,
)
from app.main import create_app


class BlockedGenerator:
    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.calls: list[str] = []

    async def generate(self, instructions: str) -> SimpleNamespace:
        self.calls.append(instructions)
        await self.release.wait()
        image = SimpleNamespace(media_type="image/png", data=PNG_SIGNATURE + b"payload")
        return SimpleNamespace(
            images=[image], image=image, model_name="reported", cost=lambda: None
        )


def test_owned_http_admission_replay_and_download(tmp_path: Path) -> None:
    async def exercise() -> None:
        generator = BlockedGenerator()
        service = ImageGenerationService(
            "gpt-image-test", tmp_path, cast(ImageGenerator, generator), None
        )
        app = create_app()
        app.state.image_generation_service = service
        owner = {"X-Application-User": "issuer:owner"}
        key = uuid4()
        headers = {**owner, "Idempotency-Key": str(key)}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            try:
                response = await client.post(
                    "/api/v1/image-generations",
                    headers=headers,
                    json={"instructions": "  exact text  "},
                )
                assert response.status_code == 202
                snapshot = response.json()
                assert snapshot["status"] == "running"
                assert snapshot["estimated_cost_usd"] is None
                location = response.headers["location"]
                assert response.headers["cache-control"] == "private, no-store"
                replay = await client.post(
                    "/api/v1/image-generations",
                    headers={**owner, "Idempotency-Key": "{" + str(key).upper() + "}"},
                    json={"instructions": "  exact text  "},
                )
                assert replay.status_code == 200
                assert replay.json()["generation_id"] == snapshot["generation_id"]
                conflict = await client.post(
                    "/api/v1/image-generations",
                    headers=headers,
                    json={"instructions": "exact text"},
                )
                assert conflict.status_code == 409
                assert (
                    conflict.json()["kind"] == "image_generation_idempotency_conflict"
                )
                assert (
                    await client.get(location + "/content", headers=owner)
                ).status_code == 409
                other = await client.get(
                    location, headers={"X-Application-User": "issuer:other"}
                )
                unknown = await client.get(
                    "/api/v1/image-generations/" + str(uuid4()), headers=owner
                )
                assert other.status_code == unknown.status_code == 404
                assert other.json() == unknown.json()
                generator.release.set()
                for _ in range(100):
                    status = await client.get(location, headers=owner)
                    if status.json()["status"] != "running":
                        break
                    await asyncio.sleep(0.01)
                assert status.json()["status"] == "completed"
                assert generator.calls == ["  exact text  "]
                for _ in range(2):
                    content = await client.get(location + "/content", headers=owner)
                    assert content.status_code == 200
                    assert content.content == PNG_SIGNATURE + b"payload"
                    assert content.headers["content-type"] == "image/png"
                    assert int(content.headers["content-length"]) == len(
                        content.content
                    )
                    assert content.headers["cache-control"] == "private, no-store"
                assert (
                    await client.get(
                        location + "/content",
                        headers={"X-Application-User": "issuer:other"},
                    )
                ).status_code == 404
            finally:
                generator.release.set()
                await service.close()

    asyncio.run(exercise())


def test_invalid_requests_do_not_reserve_key(tmp_path: Path) -> None:
    async def exercise() -> None:
        generator = BlockedGenerator()
        service = ImageGenerationService(
            "gpt-image-test", tmp_path, cast(ImageGenerator, generator), None
        )
        app = create_app()
        app.state.image_generation_service = service
        key = str(uuid4())
        owner = ("X-Application-User", "issuer:owner")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            try:
                headers = [owner, ("Idempotency-Key", key)]
                for body in (
                    {"instructions": " "},
                    {"instructions": "x", "extra": 1},
                    {"instructions": "x" * 32001},
                ):
                    assert (
                        await client.post(
                            "/api/v1/image-generations", headers=headers, json=body
                        )
                    ).status_code == 422
                for bad_headers in (
                    [owner],
                    [owner, ("Idempotency-Key", "bad")],
                    [owner, ("Idempotency-Key", key), ("Idempotency-Key", key)],
                    [("Idempotency-Key", key)],
                    [owner, owner, ("Idempotency-Key", key)],
                ):
                    response = await client.post(
                        "/api/v1/image-generations",
                        headers=bad_headers,
                        json={"instructions": "x"},
                    )
                    assert response.status_code == 422
                    assert response.headers["cache-control"] == "private, no-store"
                assert not service.records
                assert (
                    await client.post(
                        "/api/v1/image-generations",
                        headers=headers,
                        json={"instructions": "x"},
                    )
                ).status_code == 202
            finally:
                generator.release.set()
                await service.close()

    asyncio.run(exercise())


def test_completed_replay_during_closure_and_missing_content(tmp_path: Path) -> None:
    async def exercise() -> None:
        generator = BlockedGenerator()
        service = ImageGenerationService(
            "gpt-image-test", tmp_path, cast(ImageGenerator, generator), None
        )
        app = create_app()
        app.state.image_generation_service = service
        owner = {"X-Application-User": "issuer:owner"}
        headers = {**owner, "Idempotency-Key": str(uuid4())}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/image-generations", headers=headers, json={"instructions": "x"}
            )
            location = response.headers["location"]
            generator.release.set()
            for _ in range(100):
                response = await client.get(location, headers=owner)
                if response.json()["status"] == "completed":
                    break
                await asyncio.sleep(0.01)
            assert response.json()["status"] == "completed"
            await service.close()
            replay = await client.post(
                "/api/v1/image-generations", headers=headers, json={"instructions": "x"}
            )
            assert replay.status_code == 200 and replay.json()["status"] == "completed"
            assert len(generator.calls) == 1
            record = next(iter(service.records.values()))
            assert record.path is not None
            record.path.unlink()
            missing = await client.get(location + "/content", headers=owner)
            assert (
                missing.status_code == 500
                and missing.json()["kind"] == "internal_error"
            )
            assert missing.headers["cache-control"] == "private, no-store"

    asyncio.run(exercise())


def test_openapi_requires_snapshot_fields_and_submission_headers() -> None:
    document = create_app().openapi()
    schemas = document["components"]["schemas"]
    common = {
        "generation_id",
        "status",
        "created_at",
        "completed_at",
        "configured_model",
        "provider_model",
        "estimated_cost_usd",
    }
    for variant, extra in (
        ("RunningSnapshot", set()),
        ("CompletedSnapshot", {"content"}),
        ("FailedSnapshot", {"error"}),
    ):
        assert common | extra <= set(schemas[variant]["required"])
    parameters = document["paths"]["/api/v1/image-generations"]["post"]["parameters"]
    headers = {entry["name"]: entry for entry in parameters if entry["in"] == "header"}
    assert headers["X-Application-User"]["required"]
    assert headers["Idempotency-Key"]["required"]
    assert headers["Idempotency-Key"]["schema"]["format"] == "uuid"
    content = document["paths"]["/api/v1/image-generations/{generation_id}/content"][
        "get"
    ]["responses"]["200"]["content"]
    assert content["image/png"]["schema"]["format"] == "binary"


def test_owner_scoped_keys_and_failed_content(tmp_path: Path) -> None:
    class FailingGenerator:
        def __init__(self) -> None:
            self.calls = 0

        async def generate(self, instructions: str) -> SimpleNamespace:
            self.calls += 1
            raise RuntimeError("provider secret")

    async def exercise() -> None:
        generator = FailingGenerator()
        service = ImageGenerationService(
            "gpt-image-test", tmp_path, cast(ImageGenerator, generator), None
        )
        app = create_app()
        app.state.image_generation_service = service
        key = str(uuid4())
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            try:
                first = await client.post(
                    "/api/v1/image-generations",
                    headers={
                        "X-Application-User": "issuer:first",
                        "Idempotency-Key": key,
                    },
                    json={"instructions": "one"},
                )
                second = await client.post(
                    "/api/v1/image-generations",
                    headers={
                        "X-Application-User": "issuer:second",
                        "Idempotency-Key": key,
                    },
                    json={"instructions": "two"},
                )
                assert first.status_code == second.status_code == 202
                assert first.json()["generation_id"] != second.json()["generation_id"]
                await asyncio.gather(*tuple(service.tasks))
                assert generator.calls == 2
                failed = await client.get(
                    first.headers["location"] + "/content",
                    headers={"X-Application-User": "issuer:first"},
                )
                assert failed.status_code == 409
                assert failed.json()["kind"] == "image_generation_not_completed"
                assert failed.headers["cache-control"] == "private, no-store"
            finally:
                await service.close()

    asyncio.run(exercise())
