from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.support.http import HTTPResponse, HTTPTestServer, request_with_timeout


@pytest.fixture
def redirect_server() -> Iterator[HTTPTestServer]:
    server = HTTPTestServer(
        {
            "/relative": HTTPResponse(
                status=301,
                reason="Moved Permanently",
                headers={"Location": "/final"},
            ),
            "/absolute": HTTPResponse(status=301, reason="Moved Permanently"),
            "/loop": HTTPResponse(
                status=301,
                reason="Moved Permanently",
                headers={"Location": "/loop"},
            ),
            "/final": HTTPResponse(b"redirect target"),
        }
    )

    server.set_response(
        "/absolute",
        HTTPResponse(
            status=301,
            reason="Moved Permanently",
            headers={"Location": server.url("/final")},
        ),
    )

    try:
        yield server
    finally:
        server.close()


def test_follows_relative_redirect_location(
    redirect_server: HTTPTestServer,
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
    redirect_server: HTTPTestServer,
) -> None:
    content, _ = request_with_timeout(redirect_server.url("/absolute"))
    redirect_server.wait_for_requests(2)

    assert content == "redirect target"
    assert [request.path for request in redirect_server.requests] == [
        "/absolute",
        "/final",
    ]


def test_follows_absolute_redirect_to_different_server() -> None:
    target = HTTPTestServer({"/landing": HTTPResponse(b"cross host")})
    origin = HTTPTestServer(
        {
            "/start": HTTPResponse(
                status=301,
                reason="Moved Permanently",
                headers={"Location": target.url("/landing")},
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


def test_limits_redirect_loops(redirect_server: HTTPTestServer) -> None:
    with pytest.raises(RuntimeError, match="redirect"):
        request_with_timeout(redirect_server.url("/loop"))

    redirect_server.wait_for_requests(2)
    assert len(redirect_server.requests) < 20
