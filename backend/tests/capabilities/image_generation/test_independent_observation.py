import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import httpx
import pytest
from pydantic_ai.images import ImageGenerator

from app.capabilities.image_generation.service import (
    PNG_SIGNATURE,
    ImageGenerationService,
)
from app.main import create_app


class Generator:
    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.calls = 0

    async def generate(self, instructions: str) -> SimpleNamespace:
        self.calls += 1
        await self.release.wait()
        image = SimpleNamespace(media_type="image/png", data=PNG_SIGNATURE + b"data")
        return SimpleNamespace(
            images=[image], image=image, model_name="reported", cost=lambda: None
        )


def test_terminal_observation_matches_get_and_checks_owner_before_stream(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        generator = Generator()
        service = ImageGenerationService(
            "gpt-image-test", tmp_path, cast(ImageGenerator, generator), None
        )
        app = create_app()
        app.state.image_generation_service = service
        owner = {"X-Application-User": "issuer:owner"}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            try:
                submitted = await client.post(
                    "/api/v1/image-generations",
                    headers={**owner, "Idempotency-Key": str(uuid4())},
                    json={"instructions": "prompt"},
                )
                assert submitted.status_code == 202
                location = submitted.headers["location"]
                events = location + "/events"
                other = await client.get(
                    events, headers={"X-Application-User": "issuer:other"}
                )
                missing = await client.get(
                    f"/api/v1/image-generations/{uuid4()}/events", headers=owner
                )
                assert other.status_code == missing.status_code == 404
                assert other.json() == missing.json()
                assert (await client.get(events)).status_code == 422
                assert (
                    await client.get(
                        "/api/v1/image-generations/not-a-uuid/events", headers=owner
                    )
                ).status_code == 422
                assert (
                    await client.get(
                        events,
                        headers=[
                            ("X-Application-User", "issuer:owner"),
                            ("X-Application-User", "issuer:owner"),
                        ],
                    )
                ).status_code == 422
                generator.release.set()
                await asyncio.gather(*tuple(service.tasks))
                snapshot = await client.get(location, headers=owner)
                response = await asyncio.wait_for(client.get(events, headers=owner), 1)
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")
                assert response.headers["cache-control"] == "private, no-store"
                assert response.headers["x-accel-buffering"] == "no"
                frames = [
                    frame
                    for frame in response.text.replace("\r\n", "\n").split("\n\n")
                    if frame
                ]
                assert len(frames) == 1
                assert frames[0].startswith("data:")
                assert json.loads(frames[0][len("data:") :].strip()) == {
                    "kind": "snapshot",
                    "snapshot": snapshot.json(),
                }
                assert snapshot.json()["status"] == "completed"
                assert generator.calls == 1
            finally:
                generator.release.set()
                await service.close()

    asyncio.run(exercise())


def test_subscription_preserves_terminal_when_reader_is_delayed_and_unsubscribe_does_not_cancel(
    tmp_path: Path,
) -> None:
    from app.core.identity import ApplicationIdentity

    async def exercise() -> None:
        generator = Generator()
        service = ImageGenerationService(
            "gpt-image-test", tmp_path, cast(ImageGenerator, generator), None
        )
        owner = ApplicationIdentity("issuer", "owner")
        try:
            initial, _ = service.submit(owner, uuid4(), "prompt")
            subscription = service.subscribe(owner, initial.generation_id)
            assert subscription is not None
            captured, queue = subscription
            assert captured == initial
            record = service.get(owner, initial.generation_id)
            assert record is not None
            queue.put_nowait(captured)
            second = service.subscribe(owner, initial.generation_id)
            assert second is not None
            _, disconnected = second
            service.unsubscribe(record, disconnected)
            assert disconnected not in record.observers
            generator.release.set()
            await asyncio.gather(*tuple(service.tasks))
            terminal = await asyncio.wait_for(queue.get(), 1)
            assert terminal is not None and terminal.status == "completed"
            assert terminal == record.snapshot
            assert generator.calls == 1
            assert disconnected.empty()
            service.unsubscribe(record, queue)
            assert not record.observers
        finally:
            generator.release.set()
            await service.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("failure", ["headers", "snapshot", "heartbeat"])
def test_failed_send_releases_subscription_without_stopping_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from starlette.requests import ClientDisconnect
    from starlette.types import Message, Scope
    from app.capabilities.image_generation import http
    from app.capabilities.image_generation.http import ImageEventResponse

    heartbeat = http.with_heartbeats
    monkeypatch.setattr(
        http, "with_heartbeats", lambda updates: heartbeat(updates, 0.01)
    )
    from app.core.identity import ApplicationIdentity

    async def exercise() -> None:
        generator = Generator()
        service = ImageGenerationService(
            "gpt-image-test", tmp_path, cast(ImageGenerator, generator), None
        )
        owner = ApplicationIdentity("issuer", "owner")
        try:
            first, _ = service.submit(owner, uuid4(), "prompt")
            record = service.get(owner, first.generation_id)
            subscription = service.subscribe(owner, first.generation_id)
            assert record is not None and subscription is not None
            initial, queue = subscription
            response = ImageEventResponse(service, record, initial, queue)
            scope: Scope = {
                "type": "http",
                "asgi": {"version": "3.0", "spec_version": "2.4"},
            }

            async def receive() -> Message:
                await asyncio.Event().wait()
                return {"type": "http.disconnect"}

            async def send(message: Message) -> None:
                should_fail = (
                    failure == "headers"
                    and message["type"] == "http.response.start"
                    or failure == "snapshot"
                    and message.get("body", b"").startswith(b"data:")
                    or failure == "heartbeat"
                    and message.get("body") == b": heartbeat\n\n"
                )
                if should_fail:
                    raise OSError("disconnected")

            with pytest.raises(ClientDisconnect):
                await asyncio.wait_for(response(scope, receive, send), 1)
            assert queue not in record.observers
            generator.release.set()
            await asyncio.gather(*tuple(service.tasks))
            assert record.snapshot.status == "completed"
            assert generator.calls == 1
        finally:
            generator.release.set()
            await service.close()

    asyncio.run(exercise())


def test_shutdown_wakes_active_observer(tmp_path: Path) -> None:
    from app.core.identity import ApplicationIdentity

    async def exercise() -> None:
        generator = Generator()
        service = ImageGenerationService(
            "gpt-image-test", tmp_path, cast(ImageGenerator, generator), None
        )
        owner = ApplicationIdentity("issuer", "owner")
        initial, _ = service.submit(owner, uuid4(), "prompt")
        subscription = service.subscribe(owner, initial.generation_id)
        assert subscription is not None
        _, queue = subscription
        record = service.get(owner, initial.generation_id)
        assert record is not None
        await service.close()
        assert await asyncio.wait_for(queue.get(), 1) is None
        assert record.snapshot.status == "running"
        service.unsubscribe(record, queue)
        assert not record.observers

    asyncio.run(exercise())


def test_live_http_stream_delivers_initial_then_terminal_and_closes(
    tmp_path: Path,
) -> None:
    from starlette.types import Message, Scope
    from app.core.identity import ApplicationIdentity

    async def exercise() -> None:
        generator = Generator()
        service = ImageGenerationService(
            "gpt-image-test", tmp_path, cast(ImageGenerator, generator), None
        )
        app = create_app()
        app.state.image_generation_service = service
        owner = ApplicationIdentity("issuer", "owner")
        first, _ = service.submit(owner, uuid4(), "prompt")
        path = f"/api/v1/image-generations/{first.generation_id}/events"
        messages: asyncio.Queue[Message] = asyncio.Queue()
        scope: Scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "scheme": "http",
            "method": "GET",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "server": ("test", 80),
            "client": ("test", 123),
            "headers": [(b"x-application-user", b"issuer:owner")],
        }

        async def receive() -> Message:
            await asyncio.Event().wait()
            return {"type": "http.disconnect"}

        async def send(message: Message) -> None:
            await messages.put(message)

        task = asyncio.create_task(app(scope, receive, send))
        try:
            headers = await asyncio.wait_for(messages.get(), 1)
            assert headers["type"] == "http.response.start" and headers["status"] == 200
            initial = await asyncio.wait_for(messages.get(), 1)
            body = initial.get("body")
            assert isinstance(body, bytes)
            assert (
                json.loads(body.removeprefix(b"data: "))["snapshot"]["status"]
                == "running"
            )
            generator.release.set()
            terminal = await asyncio.wait_for(messages.get(), 1)
            body = terminal.get("body")
            assert isinstance(body, bytes)
            assert (
                json.loads(body.removeprefix(b"data: "))["snapshot"]["status"]
                == "completed"
            )
            end = await asyncio.wait_for(messages.get(), 1)
            assert end.get("body") == b"" and not end.get("more_body", False)
            await asyncio.wait_for(task, 1)
            record = service.get(owner, first.generation_id)
            assert record is not None and not record.observers
            assert generator.calls == 1
        finally:
            generator.release.set()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await service.close()

    asyncio.run(exercise())
