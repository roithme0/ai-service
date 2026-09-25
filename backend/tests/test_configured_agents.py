import asyncio
from datetime import UTC, datetime

from app.agents.demo import create_demo_agent, validate_demo_input
from app.agents.recipe import RecipeSessionInput, create_recipe_agent
from app.demo.session import new_demo_session_store
from app.models.agentic_generation import AgenticGenerationRequest, AgenticGenerationResponse
from app.recipe_improvement.session_lifecycle import new_recipe_session_store
from app.sessions.agent_service import AgentInputRejected
from app.sessions.conversation import ConversationReadActive

from test_recipe_improvement_session_http import FakeResolver, valid_request


class ReplyGenerator:
    def __init__(self) -> None:
        self.requests: list[AgenticGenerationRequest] = []

    async def generate(self, request: AgenticGenerationRequest) -> AgenticGenerationResponse:
        self.requests.append(request)
        return AgenticGenerationResponse((), (), "Configured reply")


def test_direct_recipe_creation_normalizes_json_and_rejects_invalid_input() -> None:
    store = new_recipe_session_store()
    agent = create_recipe_agent(ReplyGenerator(), FakeResolver(), store)
    request = valid_request()
    created = agent.create(RecipeSessionInput(request["source"], request["foodstuffs"]))
    assert not isinstance(created, AgentInputRejected)
    read = agent.read(created.session_id)
    assert isinstance(read, ConversationReadActive)
    assert str(read.snapshot.session.payload.source.recipe.ingredients[0].amount) == "125.75"

    invalid = agent.create(RecipeSessionInput({}, request["foodstuffs"]))
    assert isinstance(invalid, AgentInputRejected)
    assert invalid.issues[0].location[0] == "source"
    assert len(store._settings) == 1


def test_demo_validation_and_configured_sequence_without_model() -> None:
    pauses: list[float] = []

    async def pause(seconds: float) -> None:
        pauses.append(seconds)

    agent = create_demo_agent(delay_seconds=0.2, pause=pause)
    assert not isinstance(validate_demo_input(None), AgentInputRejected)
    assert not isinstance(validate_demo_input({}), AgentInputRejected)
    assert isinstance(agent.create({"unexpected": True}), AgentInputRejected)
    created = agent.create(None)
    assert not isinstance(created, AgentInputRejected)
    agent.append_user_message(created.session_id, "first")
    first = asyncio.run(agent.execute_turn(created.session_id))
    agent.append_user_message(created.session_id, "second")
    second = asyncio.run(agent.execute_turn(created.session_id))
    assert first.kind == second.kind == "completed"
    assert pauses == [0.2]
    assert len(second.artifacts) == 1
    assert second.artifacts[0].type == "demo.greeting"
    assert second.artifacts[0].payload.message == "Hello, World!"


def test_instances_own_sessions_and_turns_are_isolated() -> None:
    async def scenario() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()

        async def pause(seconds: float) -> None:
            if not entered.is_set():
                entered.set()
                await release.wait()

        store = new_demo_session_store(clock=lambda: datetime(2026, 9, 25, tzinfo=UTC))
        first_agent = create_demo_agent(store, delay_seconds=0.1, pause=pause)
        second_agent = create_demo_agent(delay_seconds=0)
        first = first_agent.create(None)
        second = first_agent.create(None)
        assert not isinstance(first, AgentInputRejected)
        assert not isinstance(second, AgentInputRejected)
        assert second_agent.read(first.session_id).kind == "unknown"
        first_agent.append_user_message(first.session_id, "one")
        first_agent.append_user_message(second.session_id, "two")
        task = asyncio.create_task(first_agent.execute_turn(first.session_id))
        await entered.wait()
        assert (await first_agent.execute_turn(first.session_id)).kind == "busy"
        independent = asyncio.create_task(first_agent.execute_turn(second.session_id))
        try:
            assert (await asyncio.wait_for(independent, timeout=1)).kind == "completed"
            assert not task.done()
        finally:
            release.set()
        assert (await task).kind == "completed"

    asyncio.run(scenario())


def test_recipe_instances_bind_distinct_instructions_and_sessions() -> None:
    first_generator = ReplyGenerator()
    second_generator = ReplyGenerator()
    first_agent = create_recipe_agent(first_generator, FakeResolver(), instructions="First instructions")
    second_agent = create_recipe_agent(second_generator, FakeResolver(), instructions="Second instructions")
    request = valid_request()
    first = first_agent.create(RecipeSessionInput(request["source"], request["foodstuffs"]))
    second = second_agent.create(RecipeSessionInput(request["source"], request["foodstuffs"]))
    assert not isinstance(first, AgentInputRejected)
    assert not isinstance(second, AgentInputRejected)
    assert first_agent.read(second.session_id).kind == "unknown"
    assert second_agent.read(first.session_id).kind == "unknown"
    first_agent.append_user_message(first.session_id, "one")
    second_agent.append_user_message(second.session_id, "two")
    assert asyncio.run(first_agent.execute_turn(first.session_id)).kind == "completed"
    assert asyncio.run(second_agent.execute_turn(second.session_id)).kind == "completed"
    assert first_generator.requests[0].instructions == "First instructions"
    assert second_generator.requests[0].instructions == "Second instructions"
