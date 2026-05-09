from __future__ import annotations

import socket
import threading
import time
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass, field

from netview.networking import URL


def empty_headers() -> dict[str, str]:
    return {}


@dataclass(frozen=True)
class HTTPResponse:
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=empty_headers)
    status: int = 200
    reason: str = "OK"


@dataclass(frozen=True)
class RecordedRequest:
    connection_number: int
    method: str
    path: str
    version: str
    headers: dict[str, str]


ResponseScript = HTTPResponse | Sequence[HTTPResponse]


class HTTPTestServer:
    def __init__(self, responses: dict[str, ResponseScript]) -> None:
        self._responses = responses
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen()
        self._server.settimeout(0.05)

        self.host, self.port = self._server.getsockname()
        self.requests: list[RecordedRequest] = []
        self.accepted_connections = 0

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._connections: list[socket.socket] = []
        self._workers: list[threading.Thread] = []
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def url(self, path: str) -> str:
        return f"http://{self.host}:{self.port}{path}"

    def set_response(self, path: str, response: ResponseScript) -> None:
        self._responses[path] = response

    def wait_for_requests(self, count: int, timeout: float = 1.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if len(self.requests) >= count:
                    return
            time.sleep(0.01)

        raise AssertionError(f"timed out waiting for {count} request(s)")

    def close(self) -> None:
        self._stop.set()

        for conn in self._connections:
            with suppress(OSError):
                conn.shutdown(socket.SHUT_RDWR)
            conn.close()

        self._server.close()
        self._thread.join(timeout=1.0)

        for worker in self._workers:
            worker.join(timeout=1.0)

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _addr = self._server.accept()
            except TimeoutError:
                continue
            except OSError:
                return

            with self._lock:
                self.accepted_connections += 1
                connection_number = self.accepted_connections
                self._connections.append(conn)

            conn.settimeout(0.05)
            worker = threading.Thread(
                target=self._handle_connection,
                args=(conn, connection_number),
                daemon=True,
            )
            self._workers.append(worker)
            worker.start()

    def _handle_connection(self, conn: socket.socket, connection_number: int) -> None:
        pending = b""

        while not self._stop.is_set():
            request, pending = self._read_request(conn, pending)
            if request is None:
                return

            recorded = self._record_request(request, connection_number)
            response = self._response_for(recorded.path)
            conn.sendall(self._serialize_response(response))

    def _read_request(
        self, conn: socket.socket, pending: bytes
    ) -> tuple[bytes | None, bytes]:
        data = pending

        while b"\r\n\r\n" not in data:
            if self._stop.is_set():
                return None, b""

            try:
                chunk = conn.recv(4096)
            except TimeoutError:
                continue
            except OSError:
                return None, b""

            if chunk == b"":
                return None, b""

            data += chunk

        request, rest = data.split(b"\r\n\r\n", 1)
        return request, rest

    def _record_request(
        self, request: bytes, connection_number: int
    ) -> RecordedRequest:
        lines = request.decode("iso-8859-1").split("\r\n")
        method, path, version = lines[0].split(" ", 2)
        headers: dict[str, str] = {}

        for line in lines[1:]:
            name, value = line.split(":", 1)
            headers[name.casefold()] = value.strip()

        recorded = RecordedRequest(
            connection_number=connection_number,
            method=method,
            path=path,
            version=version,
            headers=headers,
        )

        with self._lock:
            self.requests.append(recorded)

        return recorded

    def _response_for(self, path: str) -> HTTPResponse:
        script = self._responses.get(path)
        if script is None:
            return HTTPResponse(b"not found", status=404, reason="Not Found")

        if isinstance(script, HTTPResponse):
            return script

        with self._lock:
            request_count = sum(request.path == path for request in self.requests)

        index = min(request_count - 1, len(script) - 1)
        return script[index]

    def _serialize_response(self, response: HTTPResponse) -> bytes:
        header_lines = [
            f"HTTP/1.1 {response.status} {response.reason}".encode("ascii"),
            f"Content-Length: {len(response.body)}".encode("ascii"),
            b"Connection: keep-alive",
        ]

        for name, value in response.headers.items():
            header_lines.append(f"{name}: {value}".encode("ascii"))

        return b"\r\n".join(header_lines) + b"\r\n\r\n" + response.body


def request_with_timeout(url: str, timeout: float = 1.0) -> tuple[str, bool]:
    result: list[tuple[str, bool]] = []
    errors: list[BaseException] = []

    def run() -> None:
        try:
            result.append(URL(url).request())
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        raise AssertionError("URL.request() did not return before the timeout")

    if errors:
        raise errors[0]

    return result[0]


def start_background_request(url: str) -> threading.Thread:
    thread = threading.Thread(target=lambda: URL(url).request(), daemon=True)
    thread.start()
    return thread
