"""Start and fully observe a turn for model-flow assertions; never used for timing tests."""
import json
from typing import cast

from fastapi.testclient import TestClient
from httpx import Response


def observe_turn(client: TestClient, url: str, *, json_body: object = None) -> Response:
    accepted = client.post(url, json=json_body) if json_body is not None else client.post(url)
    if accepted.status_code != 202:
        return accepted
    turn_id = accepted.json()['turn_id']
    observed = client.get(f'{url}/{turn_id}/events')
    if observed.status_code != 200:
        return observed
    events = [json.loads(line[6:]) for line in observed.text.splitlines() if line.startswith('data: ')]
    terminal = next((event for event in events if event['kind'] == 'terminal'), None)
    if terminal is None:
        return Response(410, json={'kind': 'expired'})
    snapshot = client.get(url.removesuffix('/turns')).json()
    if terminal['outcome'] != 'completed':
        return Response(502, json={'detail': 'Turn generation failed', 'kind': terminal['outcome'], 'turn_id': turn_id})
    message = next(message for message in cast(list[dict[str, object]], snapshot['messages']) if message['turn_id'] == turn_id)
    return Response(200, json={'kind': 'completed', 'turn_id': turn_id, 'message': message,
        'artifacts': [artifact for artifact in snapshot['artifacts'] if artifact['turn_id'] == turn_id],
        'timeline': [item for item in snapshot['timeline'] if item['turn_id'] == turn_id and not (item['kind'] == 'message' and item['role'] == 'user')]})
