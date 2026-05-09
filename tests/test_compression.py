from __future__ import annotations

import gzip

import pytest

from tests.support.http import (
    HTTPResponse,
    HTTPTestServer,
    request_with_timeout,
    start_background_request,
)


def test_sends_accept_encoding_gzip_header() -> None:
    server = HTTPTestServer({"/": HTTPResponse(b"plain text")})

    try:
        start_background_request(server.url("/"))
        server.wait_for_requests(1)

        [request] = server.requests
        assert request.headers["accept-encoding"] == "gzip"
    finally:
        server.close()


def test_decompresses_gzip_content_encoding() -> None:
    compressed_body = gzip.compress(b"<h1>Compressed page</h1>")
    server = HTTPTestServer(
        {
            "/compressed": HTTPResponse(
                compressed_body,
                headers={"Content-Encoding": "gzip"},
            )
        }
    )

    try:
        content, view_source = request_with_timeout(server.url("/compressed"))

        assert content == "<h1>Compressed page</h1>"
        assert view_source is False
    finally:
        server.close()


def test_decompresses_gzip_content_encoding_with_chunked_transfer() -> None:
    compressed_body = gzip.compress(b"<p>chunked compressed page</p>")
    server = HTTPTestServer(
        {
            "/chunked": HTTPResponse(
                headers={
                    "Content-Encoding": "gzip",
                    "Transfer-Encoding": "chunked",
                },
                chunks=[
                    compressed_body[:8],
                    compressed_body[8:21],
                    compressed_body[21:],
                ],
            )
        }
    )

    try:
        content, _ = request_with_timeout(server.url("/chunked"))

        assert content == "<p>chunked compressed page</p>"
    finally:
        server.close()


@pytest.mark.skip(reason="transfer-encoding compression is a later exercise slice")
def test_future_decompresses_gzip_transfer_encoding() -> None:
    raise NotImplementedError


@pytest.mark.skip(reason="transfer-encoding compression is a later exercise slice")
def test_future_decompresses_deflate_transfer_encoding() -> None:
    raise NotImplementedError
