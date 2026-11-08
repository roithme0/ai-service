"""Application-owned generation registry and execution."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from openai import APITimeoutError, AsyncOpenAI
from pydantic_ai.exceptions import (
    ContentFilterError,
    ModelAPIError,
    UnexpectedModelBehavior,
)
from pydantic_ai.images import ImageGenerator
from pydantic_ai.images.openai import (
    OpenAIImageGenerationModel,
    OpenAIImageGenerationSettings,
)
from pydantic_ai.providers.openai import OpenAIProvider

from app.capabilities.image_generation import storage
from app.capabilities.image_generation.config import ImageGenerationSettings
from app.capabilities.image_generation.models import (
    CompletedSnapshot,
    Content,
    FailedSnapshot,
    Failure,
    RunningSnapshot,
    Snapshot,
)
from app.core.config import ProviderSettings
from app.core.identity import ApplicationIdentity

logger = logging.getLogger(__name__)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
DETAILS = {
    "image_generation_timeout": "Image generation timed out",
    "image_generation_rejected": "Image generation was rejected",
    "image_generation_provider_failed": "Image generation provider failed",
    "image_generation_invalid_output": "Image generation returned invalid output",
    "image_generation_storage_failed": "Image generation storage failed",
    "image_generation_failed": "Image generation failed",
}


class Unavailable(Exception):
    pass


class Conflict(Exception):
    pass


@dataclass
class Record:
    owner: ApplicationIdentity
    instructions: str
    snapshot: Snapshot
    path: Path | None = None


class ImageGenerationService:
    def __init__(
        self,
        model: str | None,
        run: Path | None,
        generator: ImageGenerator | None,
        client: AsyncOpenAI | None,
        deadline: float = 300,
    ) -> None:
        self.model, self.run, self.generator, self.client, self.deadline = (
            model,
            run,
            generator,
            client,
            deadline,
        )
        self.records: dict[UUID, Record] = {}
        self.keys: dict[tuple[ApplicationIdentity, UUID], UUID] = {}
        self.tasks: set[asyncio.Task[None]] = set()
        self.cleanups: set[asyncio.Task[None]] = set()
        self.closing = False

    @classmethod
    def create(
        cls,
        provider: ProviderSettings,
        settings: ImageGenerationSettings,
        run: Path | None,
    ) -> "ImageGenerationService":
        model = settings.image_generation_openai_model
        key = provider.openai_api_key
        client = None
        generator = None
        if model and (
            not model.startswith("gpt-image-") or len(model) == len("gpt-image-")
        ):
            logger.warning("Image generation model configuration is unsupported")
        if (
            key
            and model
            and model.startswith("gpt-image-")
            and len(model) > len("gpt-image-")
            and run
        ):
            try:
                client = AsyncOpenAI(api_key=key.get_secret_value(), max_retries=0)
                image_settings = OpenAIImageGenerationSettings(
                    openai_size="1024x1024",
                    openai_quality="medium",
                    openai_background="opaque",
                    openai_n=1,
                    openai_output_format="png",
                )
                generator = ImageGenerator(
                    OpenAIImageGenerationModel(
                        model, provider=OpenAIProvider(openai_client=client)
                    ),
                    settings=image_settings,
                    instrument=False,
                )
            except Exception:
                logger.warning("Image generation provider initialization failed")
        return cls(model, run, generator, client)

    def submit(
        self, owner: ApplicationIdentity, key: UUID, instructions: str
    ) -> tuple[Snapshot, bool]:
        association = (owner, key)
        if association in self.keys:
            record = self.records[self.keys[association]]
            if record.instructions != instructions:
                raise Conflict()
            return record.snapshot, False
        if self.closing or not self.generator or not self.run or not self.model:
            raise Unavailable()
        generation_id = uuid4()
        snapshot = RunningSnapshot(
            status="running",
            completed_at=None,
            generation_id=generation_id,
            created_at=datetime.now(UTC),
            configured_model=self.model,
            provider_model=None,
            estimated_cost_usd=None,
        )
        record = Record(owner, instructions, snapshot)
        self.records[generation_id] = record
        self.keys[association] = generation_id
        task = asyncio.create_task(
            self._execute(record, asyncio.get_running_loop().time() + self.deadline)
        )
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return snapshot, True

    def get(self, owner: ApplicationIdentity, generation_id: UUID) -> Record | None:
        record = self.records.get(generation_id)
        return record if record and record.owner == owner else None

    async def _execute(self, record: Record, deadline: float) -> None:
        assert self.generator and self.run
        base = record.snapshot
        provider_model = None
        cost = None
        kind = "image_generation_failed"
        writer: asyncio.Task[Path] | None = None
        try:
            async with asyncio.timeout_at(deadline):
                try:
                    result = await self.generator.generate(record.instructions)
                except (TimeoutError, APITimeoutError):
                    kind = "image_generation_timeout"
                    raise
                except ContentFilterError:
                    kind = "image_generation_rejected"
                    raise
                except UnexpectedModelBehavior:
                    kind = "image_generation_invalid_output"
                    raise
                except ModelAPIError as exc:
                    kind = (
                        "image_generation_timeout"
                        if isinstance(exc.__cause__, APITimeoutError)
                        else "image_generation_provider_failed"
                    )
                    raise
                except Exception:
                    kind = "image_generation_provider_failed"
                    raise
                provider_model = result.model_name or None
                try:
                    candidate = Decimal(result.cost().total_price)
                    if candidate.is_finite() and candidate >= 0:
                        cost = candidate
                except Exception:
                    pass
                if (
                    len(result.images) != 1
                    or result.image.media_type != "image/png"
                    or not result.image.data.startswith(PNG_SIGNATURE)
                ):
                    kind = "image_generation_invalid_output"
                    raise ValueError("Invalid image")
                size = len(result.image.data)
                kind = "image_generation_storage_failed"
                writer = asyncio.create_task(
                    asyncio.to_thread(
                        storage.publish, self.run, base.generation_id, result.image.data
                    )
                )
                path = await asyncio.shield(writer)
                if asyncio.get_running_loop().time() >= deadline:
                    raise TimeoutError()
                record.path = path
                record.snapshot = CompletedSnapshot(
                    status="completed",
                    generation_id=base.generation_id,
                    created_at=base.created_at,
                    completed_at=datetime.now(UTC),
                    configured_model=base.configured_model,
                    provider_model=provider_model,
                    estimated_cost_usd=cost,
                    content=Content(
                        media_type="image/png",
                        url=f"/api/v1/image-generations/{base.generation_id}/content",
                        size_bytes=size,
                    ),
                )
                return
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            kind = "image_generation_timeout"
        except Exception as exc:
            logger.warning("Image generation failed: %s", type(exc).__name__)
        finally:
            if record.snapshot.status != "completed":

                async def cleanup() -> None:
                    if writer:
                        await asyncio.gather(writer, return_exceptions=True)
                    await asyncio.to_thread(
                        storage.remove, self.run, base.generation_id
                    )

                cleanup_task = asyncio.create_task(cleanup())
                self.cleanups.add(cleanup_task)
                cleanup_task.add_done_callback(self.cleanups.discard)
        record.snapshot = FailedSnapshot(
            status="failed",
            generation_id=base.generation_id,
            created_at=base.created_at,
            completed_at=datetime.now(UTC),
            configured_model=base.configured_model,
            provider_model=provider_model,
            estimated_cost_usd=cost,
            error=Failure(kind=kind, detail=DETAILS[kind]),
        )

    async def close(self) -> None:
        self.closing = True
        for task in tuple(self.tasks):
            task.cancel()
        while self.tasks:
            pending = tuple(self.tasks)
            await asyncio.gather(*pending, return_exceptions=True)
            self.tasks.difference_update(pending)
        while self.cleanups:
            pending = tuple(self.cleanups)
            await asyncio.gather(*pending, return_exceptions=True)
            self.cleanups.difference_update(pending)
        if self.client:
            await self.client.close()
