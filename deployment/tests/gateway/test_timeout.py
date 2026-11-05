from __future__ import annotations

import json
import http.client
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

TURN_PATH = "/api/v1/agents/kochwiki/sessions/test/turns"
EVENTS_PATH = "/api/v1/agents/kochwiki/sessions/test/events"
TRANSCRIPTION_PATH = "/api/v1/transcriptions"
HEARTBEAT = b": heartbeat\n\n"
FINAL_EVENT = b'data: {"kind":"complete"}\n\n'
UPLOAD_STARTED = threading.Event()


def response_body(status: int) -> bytes:
    return json.dumps({"status": status, "reply": "Recipe turn: \u00e4"}).encode()


class TestBackend(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/test/upload-started":
            self.send_response(200 if UPLOAD_STARTED.is_set() else 204)
            self.end_headers()
            return
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
        if self.headers.get("X-Test-Observe-Upload"):
            self.rfile.read(1)
            UPLOAD_STARTED.set()
            self.rfile.read(int(self.headers["Content-Length"]) - 1)
        elif self.headers.get("Transfer-Encoding", "").lower() == "chunked":
            while True:
                line = self.rfile.readline()
                if not line:
                    return
                size = int(line.strip(), 16)
                if not size:
                    self.rfile.readline()
                    break
                self.rfile.read(size)
                self.rfile.read(2)
        else:
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
        status = int(self.headers["X-Test-Status"])
        if self.path.endswith("/silent"):
            time.sleep(65)
        if self.path == TRANSCRIPTION_PATH and self.headers.get("X-Test-Delay"):
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

    def test_transcription_allows_large_upload_and_long_provider_wait(self) -> None:
        request = Request(
            f"http://gateway{TRANSCRIPTION_PATH}",
            data=b"a" * (1024 * 1024 + 1),
            headers={"Content-Type": "audio/webm", "X-Test-Status": "201", "X-Test-Delay": "1"},
        )
        started = time.monotonic()
        with urlopen(request, timeout=90) as response:
            self.assertEqual(response.status, 201)
            self.assertEqual(response.read(), response_body(201))
        self.assertGreater(time.monotonic() - started, 60)

    def test_transcription_over_limit_has_safe_json_error(self) -> None:
        request = Request(
            f"http://gateway{TRANSCRIPTION_PATH}",
            data=b"a" * 25_000_001,
            headers={"Content-Type": "audio/webm", "X-Test-Status": "201"},
        )
        with self.assertRaises(HTTPError) as raised:
            urlopen(request, timeout=30)
        with raised.exception as response:
            self.assertEqual(response.code, 413)
            self.assertEqual(response.headers.get_content_type(), "application/json")
            self.assertEqual(json.load(response), {"kind": "audio_too_large", "detail": "Audio exceeds the size limit"})

    def test_transcription_forwards_upload_before_body_completes(self) -> None:
        connection = http.client.HTTPConnection("gateway", timeout=10)
        try:
            connection.putrequest("POST", TRANSCRIPTION_PATH)
            connection.putheader("Content-Type", "audio/webm")
            connection.putheader("Content-Length", "2")
            connection.putheader("X-Test-Status", "201")
            connection.putheader("X-Test-Observe-Upload", "1")
            connection.endheaders()
            connection.send(b"a")
            for _ in range(50):
                with urlopen("http://backend:8080/test/upload-started", timeout=2) as response:
                    if response.status == 200:
                        break
                time.sleep(0.1)
            else:
                self.fail("Gateway did not forward the incomplete upload")
            connection.send(b"b")
            self.assertEqual(connection.getresponse().status, 201)
        finally:
            connection.close()

    def test_chunked_transcription_over_limit_has_safe_json_error(self) -> None:
        connection = http.client.HTTPConnection("gateway", timeout=30)
        try:
            connection.putrequest("POST", TRANSCRIPTION_PATH)
            connection.putheader("Content-Type", "audio/webm")
            connection.putheader("Transfer-Encoding", "chunked")
            connection.putheader("X-Test-Status", "201")
            connection.endheaders()
            chunk = b"a" * 1_000_000
            for _ in range(25):
                connection.send(b"f4240\r\n" + chunk + b"\r\n")
            connection.send(b"1\r\na\r\n0\r\n\r\n")
            response = connection.getresponse()
            self.assertEqual(response.status, 413)
            self.assertEqual(response.headers.get_content_type(), "application/json")
            self.assertEqual(json.load(response), {"kind": "audio_too_large", "detail": "Audio exceeds the size limit"})
        finally:
            connection.close()


if __name__ == "__main__":
    if sys.argv[1:] == ["serve"]:
        ThreadingHTTPServer(("0.0.0.0", 8080), TestBackend).serve_forever()
    else:
        unittest.main()
