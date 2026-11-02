from __future__ import annotations

import json
import sys
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

TURN_PATH = "/api/v1/agents/kochwiki/sessions/test/turns"
EVENTS_PATH = "/api/v1/agents/kochwiki/sessions/test/events"
HEARTBEAT = b": heartbeat\n\n"
FINAL_EVENT = b'data: {"kind":"complete"}\n\n'


def response_body(status: int) -> bytes:
    return json.dumps({"status": status, "reply": "Recipe turn: \u00e4"}).encode()


class TestBackend(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        if self.path == EVENTS_PATH:
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        if self.path == EVENTS_PATH:
            for _ in range(5):
                time.sleep(15)
                self.wfile.write(HEARTBEAT)
                self.wfile.flush()
            self.wfile.write(FINAL_EVENT)
            self.wfile.flush()

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        status = int(self.headers["X-Test-Status"])
        if self.path.endswith("/silent"):
            time.sleep(65)
        body = response_body(status)
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


class GatewayTimeoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        for attempt in range(30):
            try:
                with urlopen("http://gateway/api/health", timeout=2):
                    return
            except (URLError, TimeoutError):
                if attempt == 29:
                    raise
                time.sleep(1)

    def test_heartbeats_keep_stream_open_beyond_read_timeout(self) -> None:
        started = time.monotonic()
        previous = started
        with urlopen(f"http://gateway{EVENTS_PATH}", timeout=90) as response:
            self.assertEqual(response.status, 200)
            for _ in range(5):
                self.assertEqual(response.readline(), b": heartbeat\n")
                self.assertEqual(response.readline(), b"\n")
                received = time.monotonic()
                self.assertLess(received - previous, 30)
                previous = received
            self.assertEqual(response.read(), FINAL_EVENT)
        self.assertGreater(time.monotonic() - started, 70)

    def test_silent_backend_times_out(self) -> None:
        request = Request(
            f"http://gateway{TURN_PATH}/silent",
            data=b"{}",
            headers={"Content-Type": "application/json", "X-Test-Status": "201"},
        )
        started = time.monotonic()
        with self.assertRaises(HTTPError) as raised:
            urlopen(request, timeout=90)
        with raised.exception as response:
            self.assertEqual(response.code, 504)
        elapsed = time.monotonic() - started
        self.assertGreater(elapsed, 55)
        self.assertLess(elapsed, 75)

    def test_preserves_success_and_error_responses(self) -> None:
        for status in (201, 422):
            with self.subTest(status=status):
                request = Request(
                    f"http://gateway{TURN_PATH}",
                    data=b"{}",
                    headers={
                        "Content-Type": "application/json",
                        "X-Test-Status": str(status),
                    },
                )
                try:
                    response = urlopen(request, timeout=5)
                except HTTPError as error:
                    response = error
                with response:
                    self.assertEqual(response.status, status)
                    self.assertEqual(response.read(), response_body(status))


if __name__ == "__main__":
    if sys.argv[1:] == ["serve"]:
        ThreadingHTTPServer(("0.0.0.0", 8080), TestBackend).serve_forever()
    else:
        unittest.main()
