from __future__ import annotations

import json
import sys
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DELAY_SECONDS = 65
TURN_PATH = "/api/v1/agents/kochwiki/sessions/test/turns"


def response_body(status: int) -> bytes:
    return json.dumps({"status": status, "reply": "Delayed recipe turn: ä"}).encode()


class DelayedBackend(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.end_headers()

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        status = int(self.headers["X-Test-Status"])
        time.sleep(DELAY_SECONDS)
        body = response_body(status)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def delayed_turn(status: int) -> tuple[int, bytes, float]:
    request = Request(
        f"http://gateway{TURN_PATH}", data=b"{}", method="POST",
        headers={"Content-Type": "application/json", "X-Test-Status": str(status)},
    )
    started = time.monotonic()
    try:
        with urlopen(request, timeout=90) as response:
            return response.status, response.read(), time.monotonic() - started
    except HTTPError as response:
        return response.code, response.read(), time.monotonic() - started


class GatewayTimeoutTest(unittest.TestCase):
    def test_delayed_turn_preserves_success_and_error(self) -> None:
        for attempt in range(30):
            try:
                with urlopen("http://gateway/api/health", timeout=2):
                    break
            except (URLError, TimeoutError):
                if attempt == 29:
                    raise
                time.sleep(1)

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(delayed_turn, (201, 422)))
        for expected_status, (status, body, elapsed) in zip((201, 422), results):
            with self.subTest(status=expected_status):
                self.assertGreater(elapsed, 60)
                self.assertEqual(status, expected_status)
                self.assertEqual(body, response_body(expected_status))
                print(f"Preserved HTTP {status} and exact body after {elapsed:.1f}s", flush=True)


if __name__ == "__main__":
    if sys.argv[1:] == ["serve"]:
        ThreadingHTTPServer(("0.0.0.0", 8080), DelayedBackend).serve_forever()
    else:
        unittest.main()
