import asyncio

import pytest

from app.capabilities.conversations.runner import RunnerClosedError
from app.core.identity import ApplicationIdentity
from app.demos.visual_conversation_demo import lifecycle as visual_conversation_demo_lifecycle


def test_visual_conversation_demo_body_failure_propagates_and_closes_runner() -> None:
    async def exercise() -> None:
        owner = ApplicationIdentity("test", "user")
        with pytest.raises(LookupError, match="Application failure"):
            async with visual_conversation_demo_lifecycle.visual_conversation_demo_runner() as runner:
                runner.create_session(owner=owner)
                raise LookupError("Application failure")
        with pytest.raises(RunnerClosedError):
            runner.create_session(owner=owner)

    asyncio.run(exercise())
