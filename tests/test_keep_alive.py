from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.support.http import (
    HTTPResponse,
    HTTPTestServer,
    request_with_timeout,
    start_background_request,
)


@pytest.fixture
def keep_alive_server() -> Iterator[HTTPTestServer]:
    server = HTTPTestServer(
        {
            "/first": HTTPResponse(b"hello"),
            "/second": HTTPResponse(b"world"),
            "/unicode": HTTPResponse("caf\u00e9".encode()),
        }
    )

    try:
        yield server
    finally:
        server.close()


def test_reads_only_content_length_without_waiting_for_close(
    keep_alive_server: HTTPTestServer,
) -> None:
    content, view_source = request_with_timeout(keep_alive_server.url("/first"))

    assert content == "hello"
    assert view_source is False
    keep_alive_server.wait_for_requests(1)


def test_sends_keep_alive_header(keep_alive_server: HTTPTestServer) -> None:
    start_background_request(keep_alive_server.url("/first"))
    keep_alive_server.wait_for_requests(1)

    [request] = keep_alive_server.requests
    assert request.headers["connection"].casefold() == "keep-alive"


def test_reuses_socket_for_repeated_requests_to_same_server(
    keep_alive_server: HTTPTestServer,
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
    keep_alive_server: HTTPTestServer,
) -> None:
    other_server = HTTPTestServer({"/first": HTTPResponse(b"other")})

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
    keep_alive_server: HTTPTestServer,
) -> None:
    content, _ = request_with_timeout(keep_alive_server.url("/unicode"))

    assert content == "caf\u00e9"
