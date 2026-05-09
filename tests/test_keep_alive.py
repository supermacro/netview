from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import suppress
from dataclasses import dataclass

import pytest

from netview.networking import URL


@dataclass(frozen=True)
class RecordedRequest:
    connection_number: int
    method: str
    path: str
    version: str
    headers: dict[str, str]


class KeepAliveServer:
    def __init__(self, responses: dict[str, bytes]) -> None:
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
            body = self._responses.get(recorded.path, b"not found")
            status = b"200 OK" if recorded.path in self._responses else b"404 Not Found"
            response = (
                b"HTTP/1.1 "
                + status
                + b"\r\n"
                + b"Content-Length: "
                + str(len(body)).encode("ascii")
                + b"\r\n"
                + b"Connection: keep-alive\r\n"
                + b"\r\n"
                + body
            )
            conn.sendall(response)

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


@pytest.fixture
def keep_alive_server() -> Iterator[KeepAliveServer]:
    server = KeepAliveServer(
        {
            "/first": b"hello",
            "/second": b"world",
            "/unicode": "caf\u00e9".encode(),
        }
    )

    try:
        yield server
    finally:
        server.close()


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


def test_reads_only_content_length_without_waiting_for_close(
    keep_alive_server: KeepAliveServer,
) -> None:
    content, view_source = request_with_timeout(keep_alive_server.url("/first"))

    assert content == "hello"
    assert view_source is False
    keep_alive_server.wait_for_requests(1)


def test_sends_keep_alive_header(keep_alive_server: KeepAliveServer) -> None:
    start_background_request(keep_alive_server.url("/first"))
    keep_alive_server.wait_for_requests(1)

    [request] = keep_alive_server.requests
    assert request.headers["connection"].casefold() == "keep-alive"


def test_reuses_socket_for_repeated_requests_to_same_server(
    keep_alive_server: KeepAliveServer,
) -> None:
    first_content, _ = request_with_timeout(keep_alive_server.url("/first"))
    second_content, _ = request_with_timeout(keep_alive_server.url("/second"))
    keep_alive_server.wait_for_requests(2)

    assert first_content == "hello"
    assert second_content == "world"
    assert keep_alive_server.accepted_connections == 1
    assert [request.path for request in keep_alive_server.requests] == [
        "/first",
        "/second",
    ]
    assert {request.connection_number for request in keep_alive_server.requests} == {1}


def test_does_not_reuse_socket_for_a_different_server(
    keep_alive_server: KeepAliveServer,
) -> None:
    other_server = KeepAliveServer({"/first": b"other"})

    try:
        first_content, _ = request_with_timeout(keep_alive_server.url("/first"))
        other_content, _ = request_with_timeout(other_server.url("/first"))

        assert first_content == "hello"
        assert other_content == "other"
        assert keep_alive_server.accepted_connections == 1
        assert other_server.accepted_connections == 1
    finally:
        other_server.close()


def test_content_length_counts_bytes_not_decoded_characters(
    keep_alive_server: KeepAliveServer,
) -> None:
    content, _ = request_with_timeout(keep_alive_server.url("/unicode"))

    assert content == "caf\u00e9"
