from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import suppress
from dataclasses import dataclass
from typing import cast

import pytest

import netview.networking as networking
from netview.networking import URL


@dataclass(frozen=True)
class RedirectResponse:
    status: int
    reason: str
    body: bytes = b""
    location: str | None = None


@dataclass(frozen=True)
class RecordedRequest:
    method: str
    path: str
    version: str
    headers: dict[str, str]


class RedirectServer:
    def __init__(self, responses: dict[str, RedirectResponse]) -> None:
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

    def set_response(self, path: str, response: RedirectResponse) -> None:
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
                self._connections.append(conn)

            conn.settimeout(0.05)
            worker = threading.Thread(
                target=self._handle_connection,
                args=(conn,),
                daemon=True,
            )
            self._workers.append(worker)
            worker.start()

    def _handle_connection(self, conn: socket.socket) -> None:
        pending = b""

        while not self._stop.is_set():
            request, pending = self._read_request(conn, pending)
            if request is None:
                return

            recorded = self._record_request(request)
            response = self._responses.get(
                recorded.path,
                RedirectResponse(404, "Not Found", b"not found"),
            )
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

    def _record_request(self, request: bytes) -> RecordedRequest:
        lines = request.decode("iso-8859-1").split("\r\n")
        method, path, version = lines[0].split(" ", 2)
        headers: dict[str, str] = {}

        for line in lines[1:]:
            name, value = line.split(":", 1)
            headers[name.casefold()] = value.strip()

        recorded = RecordedRequest(
            method=method,
            path=path,
            version=version,
            headers=headers,
        )

        with self._lock:
            self.requests.append(recorded)

        return recorded

    def _serialize_response(self, response: RedirectResponse) -> bytes:
        header_lines = [
            f"HTTP/1.1 {response.status} {response.reason}".encode("ascii"),
            f"Content-Length: {len(response.body)}".encode("ascii"),
            b"Connection: keep-alive",
        ]

        if response.location is not None:
            header_lines.append(f"Location: {response.location}".encode("ascii"))

        return b"\r\n".join(header_lines) + b"\r\n\r\n" + response.body


@pytest.fixture(autouse=True)
def close_persisted_sockets() -> Iterator[None]:
    persisted_sockets = cast(
        dict[str, socket.socket],
        networking.PERSISTED_SOCKETS,  # type: ignore[reportUnknownMemberType]
    )

    for persisted_socket in persisted_sockets.values():
        with suppress(OSError):
            persisted_socket.close()
    persisted_sockets.clear()

    yield

    for persisted_socket in persisted_sockets.values():
        with suppress(OSError):
            persisted_socket.close()
    persisted_sockets.clear()


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


@pytest.fixture
def redirect_server() -> Iterator[RedirectServer]:
    server = RedirectServer(
        {
            "/relative": RedirectResponse(
                301,
                "Moved Permanently",
                location="/final",
            ),
            "/absolute": RedirectResponse(
                301,
                "Moved Permanently",
                location=None,
            ),
            "/loop": RedirectResponse(
                301,
                "Moved Permanently",
                location="/loop",
            ),
            "/final": RedirectResponse(200, "OK", b"redirect target"),
        }
    )

    server.set_response(
        "/absolute",
        RedirectResponse(
            301,
            "Moved Permanently",
            location=server.url("/final"),
        ),
    )

    try:
        yield server
    finally:
        server.close()


def test_follows_relative_redirect_location(
    redirect_server: RedirectServer,
) -> None:
    content, view_source = request_with_timeout(redirect_server.url("/relative"))
    redirect_server.wait_for_requests(2)

    assert content == "redirect target"
    assert view_source is False
    assert [request.path for request in redirect_server.requests] == [
        "/relative",
        "/final",
    ]


def test_follows_absolute_redirect_location(
    redirect_server: RedirectServer,
) -> None:
    content, _ = request_with_timeout(redirect_server.url("/absolute"))
    redirect_server.wait_for_requests(2)

    assert content == "redirect target"
    assert [request.path for request in redirect_server.requests] == [
        "/absolute",
        "/final",
    ]


def test_follows_absolute_redirect_to_different_server() -> None:
    target = RedirectServer({"/landing": RedirectResponse(200, "OK", b"cross host")})
    origin = RedirectServer(
        {
            "/start": RedirectResponse(
                301,
                "Moved Permanently",
                location=target.url("/landing"),
            )
        }
    )

    try:
        content, _ = request_with_timeout(origin.url("/start"))
        origin.wait_for_requests(1)
        target.wait_for_requests(1)

        assert content == "cross host"
        assert [request.path for request in origin.requests] == ["/start"]
        assert [request.path for request in target.requests] == ["/landing"]
    finally:
        origin.close()
        target.close()


def test_limits_redirect_loops(redirect_server: RedirectServer) -> None:
    with pytest.raises(RuntimeError, match="redirect"):
        request_with_timeout(redirect_server.url("/loop"))

    redirect_server.wait_for_requests(2)
    assert len(redirect_server.requests) < 20
