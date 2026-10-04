"""Verify the live SSE boundary through an already running local gateway."""
from __future__ import annotations

import argparse
import json
import time

import httpx


def verify(base_url: str) -> None:
    with httpx.Client(base_url=base_url, timeout=10) as client:
        base = '/api/v1/agents/demo/sessions'
        session = client.post(base, json={}).json()['session_id']
        url = f'{base}/{session}'
        client.post(url + '/messages', json={'text': 'Gateway streaming check'}).raise_for_status()
        started_at = time.monotonic()
        started = client.post(url + '/turns')
        assert started.status_code == 202
        turn_id = started.json()['turn_id']
        accepted_at = time.monotonic() - started_at
        message_at: float | None = None
        terminal_at: float | None = None
        with client.stream('GET', f'{url}/turns/{turn_id}/events') as stream:
            assert stream.status_code == 200
            assert stream.headers['content-type'].startswith('text/event-stream')
            for line in stream.iter_lines():
                if not line.startswith('data: '):
                    continue
                event = json.loads(line[6:])
                if event['kind'] == 'upsert' and event['item']['kind'] == 'message' and event['item']['role'] == 'assistant':
                    message_at = time.monotonic() - started_at
                    snapshot = client.get(url).json()
                    assert snapshot['active_turn_id'] == turn_id, 'Message was buffered until turn termination'
                    assert any(item.get('id') == event['item']['id'] for item in snapshot['timeline'])
                if event['kind'] == 'terminal':
                    assert event['outcome'] == 'completed'
                    terminal_at = time.monotonic() - started_at
        assert message_at is not None and terminal_at is not None
        assert message_at < terminal_at
        print(f'Accepted at {accepted_at:.3f}s; complete message at {message_at:.3f}s while authoritative turn active; terminal at {terminal_at:.3f}s.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://localhost:8000')
    verify(parser.parse_args().base_url)
