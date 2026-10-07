from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from threading import Event, Thread

import httpx
import uvicorn
from fastapi import FastAPI
from pydantic import TypeAdapter

from app.agents.models.generation import AgenticGenerationRequest, AgenticGenerationResponse, AgenticToolCall
from app.sessions.models.artifacts import ArtifactCandidate, ArtifactToolOutput
from app.sessions.models.conversation import ConversationReadActive, ConversationSessionSettings, ConversationTurnReservation
from app.sessions.conversation import ConversationSessionStore
from app.sessions.http import AgentTransport, _context_issue, get_agent_registry, router
from app.sessions.models.http import StreamEvent
from app.sessions.model_sessions import create_model_agent
from app.sessions.models.presentation import PresentationPayload
from app.agents.models.tools import RegisteredTool, ToolInvocation
from app.agents.models.tools import LocalToolSource
from app.sessions.models.execution import ToolExecution


@contextmanager
def socket_server(application: FastAPI) -> Iterator[str]:
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    address = f'http://127.0.0.1:{listener.getsockname()[1]}'
    server = uvicorn.Server(uvicorn.Config(application, log_level='error', lifespan='off'))
    started = Event()
    original = server.startup
    async def startup(sockets: list[socket.socket] | None = None) -> None:
        await original(sockets=sockets)
        started.set()
    server.startup = startup
    thread = Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    assert started.wait(5)
    try:
        yield address
    finally:
        server.should_exit = True
        thread.join(5)
        listener.close()
        assert not thread.is_alive()


def event_lines(response: httpx.Response) -> Iterator[dict[str, object]]:
    for line in response.iter_lines():
        if line.startswith('data: '):
            value = json.loads(line[6:])
            TypeAdapter(StreamEvent).validate_python(value)
            yield value


def test_real_socket_stream_is_incremental_and_disconnect_does_not_cancel_generation_or_tools() -> None:
    provider_release, tool_release, final_release = Event(), Event(), Event()
    provider_entered, tool_entered, final_entered = Event(), Event(), Event()
    calls = 0
    tool_calls = 0
    class Generator:
        async def generate(self, request: AgenticGenerationRequest) -> AgenticGenerationResponse:
            nonlocal calls
            calls += 1
            assert request.on_output_item is not None
            if calls == 1:
                items: tuple[dict[str, object], ...] = (
                    {'type': 'message', 'role': 'assistant', 'phase': 'commentary', 'content': 'Already visible'},
                    {'type': 'message', 'role': 'assistant', 'content': 'Phase-less'},
                    {'type': 'function_call', 'call_id': 'call', 'name': 'publish', 'arguments': '{}'},
                )
                for item in items:
                    request.on_output_item(item)
                provider_entered.set()
                await asyncio.to_thread(provider_release.wait)
                return AgenticGenerationResponse(items, (AgenticToolCall('call', 'publish', '{}'),), None)
            final_entered.set()
            request.on_output_item({'type': 'message', 'role': 'assistant', 'phase': 'final_answer', 'content': 'Retained final'})
            await asyncio.to_thread(final_release.wait)
            raise RuntimeError('failure after accepted output')
    async def execute(_invocation: ToolInvocation) -> ToolExecution[ArtifactCandidate[PresentationPayload]]:
        nonlocal tool_calls
        tool_calls += 1
        tool_entered.set()
        await asyncio.to_thread(tool_release.wait)
        return ToolExecution(ArtifactToolOutput('presented'), ArtifactCandidate('json', PresentationPayload(title='Data', payload={'value': 42})))
    source = LocalToolSource((RegisteredTool('publish', {'type': 'function', 'name': 'publish'}, execute),))
    agent = create_model_agent(Generator(), tool_sources=(source,))
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[get_agent_registry] = lambda: {'kochwiki': AgentTransport(agent, lambda value: value, _context_issue)}
    try:
        with socket_server(application) as address, httpx.Client(base_url=address, timeout=5, headers={"X-Application-User": "test:user"}) as client:
            base = '/api/v1/agents/kochwiki/sessions'
            session = client.post(base, json={'input': {'context': {}}}).json()['session_id']
            url = f'{base}/{session}'
            client.post(url + '/messages', json={'text': 'Show'})
            accepted = client.post(url + '/turns')
            assert accepted.status_code == 202
            turn_id = accepted.json()['turn_id']
            assert provider_entered.wait(2) and not provider_release.is_set()
            assert client.post(url + '/turns').json() == accepted.json()
            assert client.post(url + '/messages', json={'text': 'Blocked'}).status_code == 409
            with client.stream('GET', f'{url}/turns/{turn_id}/events') as response:
                events = event_lines(response)
                initial = next(events)
                assert initial['kind'] == 'snapshot'
                assert initial['snapshot']['active_turn_status'] == 'in_progress'
                initial_items = initial['snapshot']['timeline']
                row = next(item for item in initial_items if item['kind'] == 'tool')
                assert row['status'] == 'requested'
                identity, order = f"tool-{row['execution_id']}", initial_items.index(row)
                assert tool_calls == 0
                provider_release.set()
                while True:
                    event = next(events)
                    if event['kind'] == 'upsert' and event['item']['kind'] == 'tool' and event['item']['status'] == 'running':
                        assert (event['identity'], event['order']) == (identity, order)
                        break
                assert tool_entered.wait(2)
                tool_release.set()
                while True:
                    event = next(events)
                    if event['kind'] == 'upsert' and event['item']['kind'] == 'artifact':
                        assert event['artifact']['payload']['payload'] == {'value': 42}
                        break
                assert final_entered.wait(2)
                while True:
                    event = next(events)
                    if event['kind'] == 'closing':
                        break
                # Close an observer while the backend remains paused after accepted artifacts.
            snapshot = client.get(url).json()
            assert snapshot['active_turn_id'] == turn_id
            assert snapshot['active_turn_status'] == 'closing'
            assert len(snapshot['artifacts']) == 1
            with client.stream('GET', f'{url}/turns/{turn_id}/events') as response:
                events = event_lines(response)
                catch_up = next(events)
                assert catch_up['kind'] == 'snapshot'
                assert catch_up['snapshot']['active_turn_status'] == 'closing'
                final_release.set()
                retained = list(events)
            assert retained[-1]['kind'] == 'terminal' and retained[-1]['outcome'] == 'generation_failed'
            snapshot = client.get(url).json()
            assert snapshot['active_turn_status'] is None
            assert any(item.get('text') == 'Retained final' for item in snapshot['timeline'])
            assert snapshot['timeline'][-1]['kind'] == 'failure'
            assert calls == 2 and tool_calls == 1
            assert client.post(url + '/turns').json() == accepted.json()
            with client.stream('GET', f'{url}/turns/{turn_id}/events') as response:
                terminal_before_subscribe = list(event_lines(response))
            assert terminal_before_subscribe[0]['snapshot']['timeline'] == snapshot['timeline']
            assert terminal_before_subscribe[-1]['outcome'] == 'generation_failed'
            assert calls == 2 and tool_calls == 1
    finally:
        provider_release.set(); tool_release.set(); final_release.set()


def test_atomic_subscription_preserves_every_tool_transition_and_bounded_overflow() -> None:
    async def exercise() -> None:
        from app.demo.agent import create_demo_agent
        from app.demo.session import new_demo_session_store
        store = new_demo_session_store()
        agent = create_demo_agent(store, delay_seconds=0)
        session = agent.create({}, owner="test:user").session_id
        store.append_user_message(session, 'Hello')
        reservation = store.reserve_turn(session)
        assert isinstance(reservation, ConversationTurnReservation)
        observer = agent.observe(session)
        first = await anext(observer)
        assert isinstance(first, ConversationReadActive)
        call = store.record_call(session, reservation.turn_id, AgenticToolCall('call', 'safe', '{}'))
        store.start_execution(session, call)
        store.record_result(session, call, ToolExecution('private'))
        store.fail_turn(session, reservation)
        statuses: list[str] = []
        while True:
            update = await asyncio.wait_for(anext(observer), 1)
            assert isinstance(update, ConversationReadActive)
            rows = [item for item in update.snapshot.timeline if item.kind == 'tool']
            if rows: statuses.append(rows[0].status)
            if update.snapshot.active_turn_id is None: break
        assert statuses[:3] == ['requested', 'running', 'completed']
        await observer.aclose()
        assert store._listeners == {}
        store.append_user_message(session, 'Again')
        reservation = store.reserve_turn(session)
        assert isinstance(reservation, ConversationTurnReservation)
        slow = agent.observe(session)
        await anext(slow)
        for index in range(129):
            store.record_provider_item(session, reservation.turn_id, {'type': 'message', 'role': 'assistant', 'content': str(index)})
        assert await anext(slow) is None
        await slow.aclose()
        assert store._listeners == {}
        store.fail_turn(session, reservation)
        await agent.close()
    asyncio.run(exercise())


def test_background_task_cancelled_before_first_step_releases_reserved_turn() -> None:
    async def exercise() -> None:
        from app.demo.agent import create_demo_agent
        agent = create_demo_agent(delay_seconds=1)
        session = agent.create({}, owner="test:user").session_id
        agent.append_user_message(session, 'Hello')
        started = agent.start_turn(session)
        await agent.close()
        read = agent.read(session)
        assert isinstance(read, ConversationReadActive)
        assert read.snapshot.active_turn_id is None
        assert read.snapshot.terminal_turn_id == started.turn_id
        assert read.snapshot.terminal_turn_kind == 'generation_failed'
    asyncio.run(exercise())

def test_records_arriving_after_initial_capture_before_first_delivery_are_not_lost_or_duplicated() -> None:
    async def exercise() -> None:
        from collections.abc import Callable
        from unittest.mock import patch
        from app.demo.agent import create_demo_agent
        from app.demo.session import new_demo_session_store
        store = new_demo_session_store()
        agent = create_demo_agent(store, delay_seconds=0)
        session = agent.create({}, owner="test:user").session_id
        store.append_user_message(session, 'Hello')
        turn = store.reserve_turn(session)
        assert isinstance(turn, ConversationTurnReservation)
        subscribe = store.subscribe
        def racing_subscribe(session_id: str, listener: Callable[[], None]) -> Callable[[], None]:
            detach = subscribe(session_id, listener)
            store.record_provider_item(session_id, turn.turn_id, {'type': 'message', 'role': 'assistant', 'content': 'During attachment'})
            store.fail_turn(session_id, turn)
            return detach
        with patch.object(store, 'subscribe', racing_subscribe):
            observer = agent.observe(session)
            initial = await anext(observer)
            assert isinstance(initial, ConversationReadActive)
            assert len(initial.snapshot.timeline) == 1
            seen_sequences = [initial.snapshot.sequence]
            messages: set[str] = set()
            while True:
                current = await asyncio.wait_for(anext(observer), 1)
                assert isinstance(current, ConversationReadActive)
                seen_sequences.append(current.snapshot.sequence)
                messages.update(item.id for item in current.snapshot.timeline if item.kind == 'message' and item.role == 'assistant')
                if current.snapshot.active_turn_id is None: break
            assert seen_sequences == sorted(seen_sequences)
            assert len(messages) == 1
            await observer.aclose()
        await agent.close()
    asyncio.run(exercise())


def test_observer_capacity_and_expiry_release_resources_without_extending_lifetime() -> None:
    async def exercise() -> None:
        from datetime import UTC, datetime
        from app.demo.agent import create_demo_agent
        from app.demo.session import new_demo_session_store
        from app.sessions.models.session import TextSessionReadUnknown
        now = datetime(2026, 10, 4, tzinfo=UTC)
        store = new_demo_session_store(clock=lambda: now)
        agent = create_demo_agent(store, delay_seconds=0)
        created = agent.create({}, owner="test:user")
        observers = [agent.observe(created.session_id) for _ in range(8)]
        for observer in observers:
            initial = await anext(observer)
            assert isinstance(initial, ConversationReadActive)
            assert initial.snapshot.session.expires_at == created.expires_at
        refused = agent.observe(created.session_id)
        assert await anext(refused) is None
        await refused.aclose()
        now = created.expires_at
        store.read(created.session_id)
        assert isinstance(await anext(observers[0]), TextSessionReadUnknown)
        for observer in observers: await observer.aclose()
        assert store._listeners == {} and agent.observation_available(created.session_id)
        await agent.close()
    asyncio.run(exercise())
