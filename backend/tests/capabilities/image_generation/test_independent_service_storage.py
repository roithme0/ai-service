import asyncio
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from pydantic_ai.images import ImageGenerator
from pytest import MonkeyPatch

from app.capabilities.image_generation import storage
from app.capabilities.image_generation.service import (
    PNG_SIGNATURE,
    ImageGenerationService,
)
from app.core.identity import ApplicationIdentity


class Generator:
    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.calls: list[str] = []

    async def generate(self, instructions: str) -> SimpleNamespace:
        self.calls.append(instructions)
        await self.release.wait()
        image = SimpleNamespace(media_type="image/png", data=PNG_SIGNATURE + b"data")
        return SimpleNamespace(
            images=[image],
            image=image,
            model_name="reported",
            cost=lambda: SimpleNamespace(total_price=Decimal("0.123")),
        )


def test_concurrent_keys_and_storage_failure_retains_cost(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    def fail_save(run: Path, generation_id: object, data: bytes) -> Path:
        raise OSError("secret path")

    monkeypatch.setattr(storage, "publish", fail_save)

    async def exercise() -> None:
        generator = Generator()
        service = ImageGenerationService(
            "gpt-image-test", tmp_path, cast(ImageGenerator, generator), None
        )
        owner = ApplicationIdentity("issuer", "owner")
        key = uuid4()
        try:

            async def submit(same: bool) -> str:
                snapshot, _ = service.submit(owner, key if same else uuid4(), "prompt")
                return str(snapshot.generation_id)

            ids = await asyncio.gather(
                *(submit(True) for _ in range(10)), submit(False)
            )
            assert len(set(ids[:10])) == 1
            assert ids[-1] != ids[0]
            await asyncio.sleep(0)
            assert generator.calls == ["prompt", "prompt"]
            generator.release.set()
            await asyncio.gather(*tuple(service.tasks))
            snapshot, created = service.submit(owner, key, "prompt")
            assert not created
            assert snapshot.status == "failed"
            assert snapshot.error.kind == "image_generation_storage_failed"
            assert "secret" not in snapshot.error.detail
            assert snapshot.provider_model == "reported"
            assert snapshot.estimated_cost_usd == Decimal("0.123")
        finally:
            generator.release.set()
            await service.close()

    asyncio.run(exercise())


def test_storage_cleanup_only_recognized_directories(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    stale = root / f"image-generation-run-{uuid4()}"
    stale.mkdir()
    (stale / "old.png").write_bytes(b"old")
    unrelated = root / "image-generation-run-not-a-uuid"
    unrelated.mkdir()
    (unrelated / "keep").write_bytes(b"keep")
    run = storage.initialize(root)
    assert not stale.exists()
    assert (unrelated / "keep").read_bytes() == b"keep"
    assert run.is_dir() and run.parent == root
    with pytest.raises(ValueError):
        storage.initialize(Path("relative"))


def test_storage_rejects_links_inside_stale_run(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    stale = root / f"image-generation-run-{uuid4()}"
    stale.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").write_bytes(b"keep")
    try:
        (stale / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Creating directory symlinks is unavailable")
    with pytest.raises(ValueError):
        storage.initialize(root)
    assert (outside / "keep").read_bytes() == b"keep"


def test_reparse_point_detection_and_cleanup_boundaries(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    linked_run = root / f"image-generation-run-{uuid4()}"
    linked_run.mkdir()
    (linked_run / "keep").write_bytes(b"keep")
    original_lstat = Path.lstat

    def reparse_lstat(path: Path) -> object:
        info = original_lstat(path)
        if path == linked_run:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
        return info

    monkeypatch.setattr(Path, "lstat", reparse_lstat)
    assert storage.is_link(linked_run)
    storage.initialize(root)
    assert (linked_run / "keep").read_bytes() == b"keep"
    monkeypatch.setattr(Path, "lstat", original_lstat)
    nested = linked_run / "nested"
    nested.mkdir()

    def nested_reparse_lstat(path: Path) -> object:
        info = original_lstat(path)
        if path == nested:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
        return info

    monkeypatch.setattr(Path, "lstat", nested_reparse_lstat)
    with pytest.raises(ValueError, match="Unsafe"):
        storage.initialize(root)
    assert (linked_run / "keep").exists()


def test_provider_deadline_fails_and_replay_recovers(tmp_path: Path) -> None:
    async def exercise() -> None:
        generator = Generator()
        service = ImageGenerationService(
            "gpt-image-test",
            tmp_path,
            cast(ImageGenerator, generator),
            None,
            deadline=0.02,
        )
        owner = ApplicationIdentity("issuer", "owner")
        key = uuid4()
        snapshot, _ = service.submit(owner, key, "prompt")
        try:
            await asyncio.gather(*tuple(service.tasks))
            replay, created = service.submit(owner, key, "prompt")
            assert not created
            assert replay.generation_id == snapshot.generation_id
            assert replay.status == "failed"
            assert replay.error.kind == "image_generation_timeout"
            assert replay.estimated_cost_usd is None
            assert generator.calls == ["prompt"]
        finally:
            generator.release.set()
            await service.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("mode", ["count", "format"])
def test_invalid_output_count_and_format_fail(tmp_path: Path, mode: str) -> None:
    class InvalidGenerator:
        async def generate(self, instructions: str) -> SimpleNamespace:
            image = SimpleNamespace(
                media_type="image/jpeg" if mode == "format" else "image/png",
                data=PNG_SIGNATURE + b"x",
            )
            return SimpleNamespace(
                images=[image, image] if mode == "count" else [image],
                image=image,
                model_name="reported",
                cost=lambda: None,
            )

    async def exercise() -> None:
        service = ImageGenerationService(
            "gpt-image-test", tmp_path, cast(ImageGenerator, InvalidGenerator()), None
        )
        owner = ApplicationIdentity("issuer", "owner")
        snapshot, _ = service.submit(owner, uuid4(), "prompt")
        try:
            await asyncio.gather(*tuple(service.tasks))
            record = service.get(owner, snapshot.generation_id)
            assert record is not None and record.snapshot.status == "failed"
            assert record.snapshot.error.kind == "image_generation_invalid_output"
        finally:
            await service.close()

    asyncio.run(exercise())


def test_shutdown_cancels_active_provider_and_rejects_new_work(tmp_path: Path) -> None:
    from app.capabilities.image_generation.service import Unavailable

    async def exercise() -> None:
        generator = Generator()
        service = ImageGenerationService(
            "gpt-image-test", tmp_path, cast(ImageGenerator, generator), None
        )
        owner = ApplicationIdentity("issuer", "owner")
        service.submit(owner, uuid4(), "prompt")
        await asyncio.sleep(0)
        assert generator.calls == ["prompt"]
        await asyncio.wait_for(service.close(), 1)
        assert not service.tasks and not service.cleanups
        with pytest.raises(Unavailable):
            service.submit(owner, uuid4(), "new")

    asyncio.run(exercise())
