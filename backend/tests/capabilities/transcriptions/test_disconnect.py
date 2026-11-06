import pytest
from starlette.types import Receive

from app.capabilities.transcriptions.service import TranscriptionService


def test_disconnect_cancels_and_drains_provider_operation() -> None:
    import asyncio
    from typing import cast

    from starlette.requests import ClientDisconnect, Request

    from app.capabilities.transcriptions.http import transcribe
    from app.capabilities.transcriptions.service import TranscriptionFailed

    async def run() -> None:
        started = asyncio.Event()
        stopped = asyncio.Event()
        messages = 0

        async def receive() -> dict[str, object]:
            nonlocal messages
            messages += 1
            if messages == 1:
                return {"type": "http.request", "body": b"audio", "more_body": False}
            await started.wait()
            return {"type": "http.disconnect"}

        class Provider:
            async def transcribe(
                self, audio: bytes, media_type: str, suffix: str
            ) -> str:
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()
                    raise TranscriptionFailed()

        request = Request(
            {"type": "http", "headers": [(b"content-type", b"audio/ogg")]},
            cast(Receive, receive),
        )
        with pytest.raises(ClientDisconnect):
            await transcribe(request, cast(TranscriptionService, Provider()))
        assert stopped.is_set()

    asyncio.run(run())


def test_request_cancellation_drains_provider_even_if_it_fails() -> None:
    import asyncio
    from typing import cast

    from starlette.requests import Request

    from app.capabilities.transcriptions.http import transcribe
    from app.capabilities.transcriptions.service import TranscriptionFailed

    async def run() -> None:
        started = asyncio.Event()
        stopped = asyncio.Event()
        messages = 0

        async def receive() -> dict[str, object]:
            nonlocal messages
            messages += 1
            if messages == 1:
                return {"type": "http.request", "body": b"audio", "more_body": False}
            await asyncio.Event().wait()
            return {"type": "http.disconnect"}

        class Provider:
            async def transcribe(
                self, audio: bytes, media_type: str, suffix: str
            ) -> str:
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()
                    raise TranscriptionFailed()

        request = Request(
            {"type": "http", "headers": [(b"content-type", b"audio/ogg")]},
            cast(Receive, receive),
        )
        task = asyncio.create_task(
            transcribe(request, cast(TranscriptionService, Provider()))
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stopped.is_set()

    asyncio.run(run())


def test_disconnect_during_upload_never_invokes_provider() -> None:
    import asyncio
    from typing import cast

    from starlette.requests import ClientDisconnect, Request

    from app.capabilities.transcriptions.http import transcribe

    async def run() -> None:
        calls = 0

        async def receive() -> dict[str, object]:
            return {"type": "http.disconnect"}

        class Provider:
            async def transcribe(
                self, audio: bytes, media_type: str, suffix: str
            ) -> str:
                nonlocal calls
                calls += 1
                return "unexpected"

        request = Request(
            {"type": "http", "headers": [(b"content-type", b"audio/ogg")]},
            cast(Receive, receive),
        )
        with pytest.raises(ClientDisconnect):
            await transcribe(request, cast(TranscriptionService, Provider()))
        assert calls == 0

    asyncio.run(run())


@pytest.mark.parametrize("overflow", [False, True])
def test_multi_chunk_upload_enforces_cap_before_reading_more(overflow: bool) -> None:
    import asyncio
    from typing import cast

    from fastapi.responses import JSONResponse
    from starlette.requests import Request

    from app.capabilities.transcriptions.http import MAX_AUDIO_BYTES, transcribe
    from app.capabilities.transcriptions.models import TranscriptionResponse

    async def run() -> None:
        reads = 0
        received_sizes: list[int] = []
        chunks = [b"a" * 12_000_000, b"b" * 13_000_000]
        if overflow:
            chunks.append(b"x")

        async def receive() -> dict[str, object]:
            nonlocal reads
            reads += 1
            if reads <= len(chunks):
                return {
                    "type": "http.request",
                    "body": chunks[reads - 1],
                    "more_body": overflow or reads < len(chunks),
                }
            if overflow:
                raise AssertionError("Read beyond the overflow chunk")
            await asyncio.Event().wait()
            return {"type": "http.disconnect"}

        class Provider:
            async def transcribe(
                self, audio: bytes, media_type: str, suffix: str
            ) -> str:
                received_sizes.append(len(audio))
                return "ok"

        request = Request(
            {"type": "http", "headers": [(b"content-type", b"audio/ogg")]},
            cast(Receive, receive),
        )
        response = await transcribe(request, cast(TranscriptionService, Provider()))
        if overflow:
            assert isinstance(response, JSONResponse)
            assert response.status_code == 413
            assert reads == 3
            assert not received_sizes
        else:
            assert isinstance(response, TranscriptionResponse)
            assert response.text == "ok"
            assert received_sizes == [MAX_AUDIO_BYTES]

    asyncio.run(run())
