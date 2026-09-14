import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.models.agentic_generation import AgenticGenerationRequest, AgenticGenerationResponse, AgenticToolCall
from app.recipe_improvement.session_input import RecipeImprovementSessionInput, RecipeImprovementSessionInputSuccess, validate_recipe_improvement_session_input
from app.recipe_improvement.session_lifecycle import RecipeImprovementSessionLookupSuccess, RecipeImprovementSessionStore


def session_input() -> RecipeImprovementSessionInput:
    result = validate_recipe_improvement_session_input(
        {"external_reference": "3fa85f64-5717-4562-b3fc-2c963f66afa6", "recipe": {
            "name": "Oats", "servings": 2, "ingredients": [
                {"index": 1, "amount": Decimal("1.25"), "foodstuff_reference": 1}],
            "steps": [{"index": 1, "description": "Mix"}]}},
        [{"external_reference": 1, "name": "Oats", "brand": None, "unit": "G"}],
    )
    assert isinstance(result, RecipeImprovementSessionInputSuccess)
    return result.session_input


def candidate(name: str = "Oats") -> dict[str, object]:
    return {"name": name, "servings": 2, "ingredients": [
        {"index": 1, "amount": "1.25", "foodstuff_reference": 1}],
        "steps": [{"index": 1, "description": "Mix"}]}


def call(call_id: str, base: dict[str, object], recipe: dict[str, object], name: str = "register_recipe_proposal") -> AgenticGenerationResponse:
    arguments = json.dumps({"base": base, "candidate": recipe})
    item = {"type": "function_call", "call_id": call_id, "name": name, "arguments": arguments}
    return AgenticGenerationResponse((item,), (AgenticToolCall(call_id, name, arguments),), None)


class ScriptedGenerator:
    def __init__(self, steps: list[AgenticGenerationResponse | Callable[[AgenticGenerationRequest], AgenticGenerationResponse]]) -> None:
        self.steps = steps
        self.requests: list[AgenticGenerationRequest] = []

    async def generate(self, request: AgenticGenerationRequest) -> AgenticGenerationResponse:
        self.requests.append(request)
        step = self.steps.pop(0)
        return step(request) if callable(step) else step


def final(text: str = "Done") -> AgenticGenerationResponse:
    return AgenticGenerationResponse((), (), text)


def test_multiple_proposals_can_chain_and_remain_typed_in_session() -> None:
    store = RecipeImprovementSessionStore(clock=lambda: datetime(2026, 9, 13, tzinfo=UTC))
    created = store.create(session_input())
    store.append_user_message(created.session_id, "Give me two options")

    def second(request: AgenticGenerationRequest) -> AgenticGenerationResponse:
        result = json.loads(request.input_items[-1]["output"])
        return call("second", {"kind": "proposal", "proposal_id": result["proposal_id"]}, candidate("Second"))

    generator = ScriptedGenerator([call("first", {"kind": "source"}, candidate("First")), second, final()])
    outcome = asyncio.run(store.generate_agentic_turn(created.session_id, generator))
    read = store.lookup(created.session_id)

    assert outcome.kind == "completed"
    assert len(outcome.proposals) == 2
    assert [proposal.order for proposal in outcome.proposals] == [1, 2]
    assert outcome.proposals[1].base.proposal_id == outcome.proposals[0].proposal_id
    assert all(proposal.turn_id == outcome.turn_id for proposal in outcome.proposals)
    assert outcome.proposals[0].recipe.ingredients[0].amount == Decimal("1.25")
    assert isinstance(read, RecipeImprovementSessionLookupSuccess)
    assert read.session.proposals == outcome.proposals
    assert len(read.session.messages) == 2


def test_later_turn_receives_full_previous_proposals_and_final_text_instruction() -> None:
    store = RecipeImprovementSessionStore()
    created = store.create(session_input())
    store.append_user_message(created.session_id, "Suggest an option")
    first = asyncio.run(store.generate_agentic_turn(
        created.session_id,
        ScriptedGenerator([call("first", {"kind": "source"}, candidate("First")), final("Option ready")]),
    ))
    assert first.kind == "completed"

    store.append_user_message(created.session_id, "Refine that proposal")

    def inspect_context(request: AgenticGenerationRequest) -> AgenticGenerationResponse:
        context = json.loads(request.input_items[0]["content"].split("\n", 1)[1])
        assert context["proposals"] == [first.proposals[0].model_dump(mode="json")]
        assert context["proposals"][0]["recipe"]["name"] == "First"
        assert "not persisted or visible to the user" in request.instructions
        assert "final text response" in request.instructions
        return final("Refined")

    second = asyncio.run(store.generate_agentic_turn(created.session_id, ScriptedGenerator([inspect_context])))
    assert second.kind == "completed"


def test_rejected_call_can_be_corrected_and_failed_final_drops_proposals() -> None:
    store = RecipeImprovementSessionStore()
    created = store.create(session_input())
    store.append_user_message(created.session_id, "Improve it")

    def correction(request: AgenticGenerationRequest) -> AgenticGenerationResponse:
        result = json.loads(request.input_items[-1]["output"])
        assert result["kind"] == "rejected"
        assert result["reason"] == "invalid_candidate"
        return call("corrected", {"kind": "source"}, candidate())

    generator = ScriptedGenerator([
        call("bad", {"kind": "source"}, candidate() | {"ingredients": [{"index": 1, "amount": "1", "foodstuff_reference": 999}]}),
        correction, final("  "),
    ])
    first = asyncio.run(store.generate_agentic_turn(created.session_id, generator))
    retry = asyncio.run(store.generate_agentic_turn(created.session_id, generator))
    assert first.kind == "generation_failed"
    assert retry == first
    assert len(generator.requests) == 3
    assert first.proposals == ()
    read = store.lookup(created.session_id)
    assert isinstance(read, RecipeImprovementSessionLookupSuccess)
    assert read.session.terminal_turn_id == first.turn_id
    assert read.session.terminal_turn_kind == "generation_failed"
    assert read.session.proposals == ()
    assert len(read.session.messages) == 1
    assert store.append_user_message(created.session_id, " ").kind == "invalid_message"
    unchanged = store.lookup(created.session_id)
    assert isinstance(unchanged, RecipeImprovementSessionLookupSuccess)
    assert unchanged.session.terminal_turn_id == first.turn_id
    assert store.append_user_message(created.session_id, "New question").kind == "accepted"
    pending = store.lookup(created.session_id)
    assert isinstance(pending, RecipeImprovementSessionLookupSuccess)
    assert pending.session.terminal_turn_id is None
    assert pending.session.terminal_turn_kind is None
    assert pending.session.proposals == ()
    def inspect_recovered_context(request: AgenticGenerationRequest) -> AgenticGenerationResponse:
        context = json.loads(request.input_items[0]["content"].split("\n", 1)[1])
        assert "proposals" not in context
        return final()

    next_turn = asyncio.run(store.generate_agentic_turn(
        created.session_id, ScriptedGenerator([inspect_recovered_context])
    ))
    assert next_turn.kind == "completed"
    assert next_turn.turn_id != first.turn_id


def test_invalid_base_returns_structured_error_before_correction() -> None:
    store = RecipeImprovementSessionStore()
    created = store.create(session_input())
    store.append_user_message(created.session_id, "Improve it")

    def correction(request: AgenticGenerationRequest) -> AgenticGenerationResponse:
        rejected = json.loads(request.input_items[-1]["output"])
        assert rejected == {"kind": "rejected", "reason": "invalid_base", "issues": []}
        return call("corrected", {"kind": "source"}, candidate())

    generator = ScriptedGenerator([
        call("bad-base", {"kind": "proposal", "proposal_id": "missing"}, candidate()),
        correction, final(),
    ])
    outcome = asyncio.run(store.generate_agentic_turn(created.session_id, generator))
    assert outcome.kind == "completed"
    assert len(outcome.proposals) == 1
    assert outcome.proposals[0].order == 1


def test_success_cap_blocks_fourth_registration() -> None:
    store = RecipeImprovementSessionStore()
    created = store.create(session_input())
    store.append_user_message(created.session_id, "Four options")
    generator = ScriptedGenerator([call(str(i), {"kind": "source"}, candidate(str(i))) for i in range(4)] + [final()])
    outcome = asyncio.run(store.generate_agentic_turn(created.session_id, generator))
    assert outcome.kind == "completed"
    assert len(outcome.proposals) == 3
    assert json.loads(generator.requests[-1].input_items[-1]["output"])["kind"] == "limit_reached"


def test_six_attempt_cap_blocks_seventh_registration() -> None:
    store = RecipeImprovementSessionStore()
    created = store.create(session_input())
    store.append_user_message(created.session_id, "Try")
    invalid = candidate() | {"ingredients": [{"index": 1, "amount": "1", "foodstuff_reference": 999}]}
    generator = ScriptedGenerator([
        call(str(i), {"kind": "source"}, invalid)
        for i in range(7)
    ] + [final()])
    outcome = asyncio.run(store.generate_agentic_turn(created.session_id, generator))
    assert outcome.kind == "completed"
    assert outcome.proposals == ()
    assert json.loads(generator.requests[-1].input_items[-1]["output"])["kind"] == "limit_reached"


def test_unknown_tool_is_rejected_without_registration() -> None:
    store = RecipeImprovementSessionStore()
    created = store.create(session_input())
    store.append_user_message(created.session_id, "Try")
    generator = ScriptedGenerator([call("bad", {"kind": "source"}, candidate(), name="unknown"), final()])
    outcome = asyncio.run(store.generate_agentic_turn(created.session_id, generator))
    assert outcome.kind == "completed"
    assert outcome.proposals == ()
    assert json.loads(generator.requests[-1].input_items[-1]["output"])["reason"] == "unknown_tool"


def test_active_turn_is_busy_but_independent_session_can_complete() -> None:
    store = RecipeImprovementSessionStore()
    first = store.create(session_input())
    second = store.create(session_input())
    store.append_user_message(first.session_id, "First")
    store.append_user_message(second.session_id, "Second")

    entered = asyncio.Event()
    release = asyncio.Event()

    class BlockingGenerator:
        async def generate(self, request: AgenticGenerationRequest) -> AgenticGenerationResponse:
            entered.set()
            await release.wait()
            return final()

    async def run() -> None:
        first_task = asyncio.create_task(store.generate_agentic_turn(first.session_id, BlockingGenerator()))
        await entered.wait()
        busy = await store.generate_agentic_turn(first.session_id, ScriptedGenerator([final()]))
        independent = await store.generate_agentic_turn(second.session_id, ScriptedGenerator([final()]))
        assert busy.kind == "busy"
        assert store.append_user_message(first.session_id, "Blocked").kind == "busy"
        assert independent.kind == "completed"
        release.set()
        assert (await first_task).kind == "completed"

    asyncio.run(run())


def test_provider_response_budget_drops_accepted_proposals() -> None:
    store = RecipeImprovementSessionStore()
    created = store.create(session_input())
    store.append_user_message(created.session_id, "Try")
    invalid = candidate() | {"ingredients": [{"index": 1, "amount": "1", "foodstuff_reference": 999}]}
    generator = ScriptedGenerator([call("accepted", {"kind": "source"}, candidate())] + [
        call(str(i), {"kind": "source"}, invalid) for i in range(7)
    ])
    result = asyncio.run(store.generate_agentic_turn(created.session_id, generator))
    assert result.kind == "generation_failed"
    assert result.proposals == ()
    read = store.lookup(created.session_id)
    assert isinstance(read, RecipeImprovementSessionLookupSuccess)
    assert read.session.proposals == ()
    assert len(generator.requests) == 8


def test_provider_exception_after_registration_drops_proposal(caplog: pytest.LogCaptureFixture) -> None:
    store = RecipeImprovementSessionStore()
    created = store.create(session_input())
    store.append_user_message(created.session_id, "Suggest an option")

    def fail_after_registration(request: AgenticGenerationRequest) -> AgenticGenerationResponse:
        raise RuntimeError("provider failed")

    generator = ScriptedGenerator([
        call("accepted", {"kind": "source"}, candidate()), fail_after_registration,
    ])
    result = asyncio.run(store.generate_agentic_turn(created.session_id, generator))
    read = store.lookup(created.session_id)

    assert result.kind == "generation_failed"
    assert result.proposals == ()
    assert isinstance(read, RecipeImprovementSessionLookupSuccess)
    assert read.session.proposals == ()
    assert f"session_id={created.session_id}, turn_id={result.turn_id}" in caplog.text
    assert "provider failed" in caplog.text


def test_cancellation_after_registration_releases_turn_and_drops_proposal() -> None:
    store = RecipeImprovementSessionStore()
    created = store.create(session_input())
    store.append_user_message(created.session_id, "Suggest an option")
    entered = asyncio.Event()

    class BlockingGenerator:
        def __init__(self) -> None:
            self.calls = 0

        async def generate(self, request: AgenticGenerationRequest) -> AgenticGenerationResponse:
            self.calls += 1
            if self.calls == 1:
                return call("accepted", {"kind": "source"}, candidate())
            entered.set()
            await asyncio.Event().wait()
            return final()

    async def run() -> None:
        task = asyncio.create_task(store.generate_agentic_turn(created.session_id, BlockingGenerator()))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    read = store.lookup(created.session_id)
    assert isinstance(read, RecipeImprovementSessionLookupSuccess)
    assert read.session.proposals == ()
    assert read.session.terminal_turn_kind == "generation_failed"
    assert store.append_user_message(created.session_id, "Try again").kind == "accepted"


def test_expiry_after_registration_drops_proposal_and_wins_over_busy() -> None:
    class Clock:
        value = datetime(2026, 9, 13, tzinfo=UTC)

        def now(self) -> datetime:
            return self.value

    clock = Clock()
    store = RecipeImprovementSessionStore(clock=clock.now)
    created = store.create(session_input())
    store.append_user_message(created.session_id, "Improve it")

    def expire(request: AgenticGenerationRequest) -> AgenticGenerationResponse:
        clock.value = created.expires_at
        assert store.append_user_message(created.session_id, "Too late").kind == "expired"
        return final()

    generator = ScriptedGenerator([call("accepted", {"kind": "source"}, candidate()), expire])
    result = asyncio.run(store.generate_agentic_turn(created.session_id, generator))
    assert result.kind in ("expired", "unknown")
    assert result.proposals == ()
