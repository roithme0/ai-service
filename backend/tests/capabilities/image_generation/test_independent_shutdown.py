import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

from pydantic_ai.images import ImageGenerator
from pytest import MonkeyPatch

from app.capabilities.image_generation import storage
from app.capabilities.image_generation.service import (
    PNG_SIGNATURE,
    ImageGenerationService,
)
from app.core.identity import ApplicationIdentity


class ImmediateGenerator:
    async def generate(self, instructions: str) -> SimpleNamespace:
        image = SimpleNamespace(media_type="image/png", data=PNG_SIGNATURE + b"payload")
        return SimpleNamespace(
            images=[image], image=image, model_name="provider-model", cost=lambda: None
        )


def test_shutdown_waits_for_timed_out_writer_and_removes_late_file(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    started = threading.Event()
    release = threading.Event()
    original_publish = storage.publish

    def blocked_publish(run: Path, generation_id: UUID, data: bytes) -> Path:
        started.set()
        if not release.wait(5):
            raise TimeoutError("test did not release writer")
        return original_publish(run, generation_id, data)

    monkeypatch.setattr(storage, "publish", blocked_publish)

    async def exercise() -> None:
        service = ImageGenerationService(
            "gpt-image-test",
            tmp_path,
            cast(ImageGenerator, ImmediateGenerator()),
            None,
            deadline=0.05,
        )
        owner = ApplicationIdentity("issuer", "subject")
        snapshot, _ = service.submit(owner, uuid4(), "prompt")
        try:
            assert await asyncio.to_thread(started.wait, 2)
            for _ in range(100):
                record = service.get(owner, snapshot.generation_id)
                assert record is not None
                if record.snapshot.status == "failed":
                    break
                await asyncio.sleep(0.01)
            assert record.snapshot.status == "failed"
            assert record.snapshot.error.kind == "image_generation_timeout"
            closing = asyncio.create_task(service.close())
            await asyncio.sleep(0.05)
            assert (
                not closing.done()
            ), "shutdown returned while the local write was still active"
        finally:
            release.set()
        await asyncio.wait_for(closing, 2)
        assert list(tmp_path.iterdir()) == []
        assert record.snapshot.status == "failed"

    asyncio.run(exercise())
