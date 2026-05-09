from __future__ import annotations

import socket
from collections.abc import Iterator
from contextlib import suppress
from typing import cast

import pytest

import netview.networking as networking


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
