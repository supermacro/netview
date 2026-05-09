from __future__ import annotations

import pytest

from tests.support.http import HTTPResponse, HTTPTestServer, request_with_timeout


def test_caches_200_get_response_without_cache_control() -> None:
    server = HTTPTestServer(
        {
            "/asset.css": [
                HTTPResponse(b"body { color: green; }"),
                HTTPResponse(b"body { color: red; }"),
            ]
        }
    )

    try:
        first_content, _ = request_with_timeout(server.url("/asset.css"))
        second_content, _ = request_with_timeout(server.url("/asset.css"))

        assert first_content == "body { color: green; }"
        assert second_content == "body { color: green; }"
        assert [request.path for request in server.requests] == ["/asset.css"]
    finally:
        server.close()


@pytest.mark.skip(reason="max-age support will be implemented later")
def test_caches_200_get_response_with_max_age() -> None:
    server = HTTPTestServer(
        {
            "/script.js": [
                HTTPResponse(
                    b"console.log('cached');",
                    headers={"Cache-Control": "max-age=60"},
                ),
                HTTPResponse(b"console.log('changed');"),
            ]
        }
    )

    try:
        first_content, _ = request_with_timeout(server.url("/script.js"))
        second_content, _ = request_with_timeout(server.url("/script.js"))

        assert first_content == "console.log('cached');"
        assert second_content == "console.log('cached');"
        assert [request.path for request in server.requests] == ["/script.js"]
    finally:
        server.close()


def test_does_not_cache_no_store_response() -> None:
    server = HTTPTestServer(
        {
            "/page": [
                HTTPResponse(b"first", headers={"Cache-Control": "no-store"}),
                HTTPResponse(b"second", headers={"Cache-Control": "no-store"}),
            ]
        }
    )

    try:
        first_content, _ = request_with_timeout(server.url("/page"))
        second_content, _ = request_with_timeout(server.url("/page"))

        assert first_content == "first"
        assert second_content == "second"
        assert [request.path for request in server.requests] == ["/page", "/page"]
    finally:
        server.close()


@pytest.mark.skip(reason="max-age support will be implemented later")
def test_does_not_cache_max_age_zero_response() -> None:
    server = HTTPTestServer(
        {
            "/freshness": [
                HTTPResponse(
                    b"stale immediately",
                    headers={"Cache-Control": "max-age=0"},
                ),
                HTTPResponse(b"refetched"),
            ]
        }
    )

    try:
        first_content, _ = request_with_timeout(server.url("/freshness"))
        second_content, _ = request_with_timeout(server.url("/freshness"))

        assert first_content == "stale immediately"
        assert second_content == "refetched"
        assert [request.path for request in server.requests] == [
            "/freshness",
            "/freshness",
        ]
    finally:
        server.close()


def test_does_not_cache_unknown_cache_control_directive() -> None:
    server = HTTPTestServer(
        {
            "/unknown": [
                HTTPResponse(
                    b"first",
                    headers={"Cache-Control": "max-age=60, private"},
                ),
                HTTPResponse(b"second"),
            ]
        }
    )

    try:
        first_content, _ = request_with_timeout(server.url("/unknown"))
        second_content, _ = request_with_timeout(server.url("/unknown"))

        assert first_content == "first"
        assert second_content == "second"
        assert [request.path for request in server.requests] == [
            "/unknown",
            "/unknown",
        ]
    finally:
        server.close()


@pytest.mark.skip(reason="v1 only caches 200 responses")
def test_future_can_cache_permanent_redirects() -> None:
    raise NotImplementedError


@pytest.mark.skip(reason="v1 does not implement validator-based revalidation")
def test_future_revalidates_with_etag() -> None:
    raise NotImplementedError
