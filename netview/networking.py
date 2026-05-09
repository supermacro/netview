import logging
import socket
import ssl
from dataclasses import dataclass
from pathlib import Path
from time import time
from urllib.parse import unquote

logger = logging.getLogger(__name__)

UA = "NetView/0.1"


@dataclass
class CacheEntry:
    content: str
    expires_at: int | None


PERSISTED_SOCKETS = {}
CONTENT_CACHE = {}


def crlf(s="", *, as_bytes: bool = False):
    val = s + "\r\n"

    if as_bytes:
        return val.encode()

    return val


class URL:
    scheme: str

    host: str | None
    port: int | None
    path: str | None

    content: str | None

    view_source: bool = False

    def __init__(self, url: str):
        self._set_defaults()

        if url.startswith("view-source:"):
            _, url = url.split(":", 1)
            self.view_source = True

        if url.startswith("data:"):
            self.scheme, rest = url.split(":", 1)

        if not self.scheme:
            self.scheme, rest = url.split("://", 1)

        assert self.scheme in ["http", "https", "file", "data"]

        if self.scheme == "data":
            mimetype, content = rest.split(",")

            if mimetype != "text/html":
                raise NotImplementedError("only text/html mimetype supported")

            self.content = unquote(content)
            self.host = None
            self.port = None
            self.path = None

            return

        if self.scheme == "file":
            self.host = None
            self.port = None
            self.path = rest
            return

        if "/" not in rest:
            rest = rest + "/"

        self.host, path = rest.split("/", 1)

        if ":" in self.host:
            self.host, port = self.host.split(":", 1)
            self.port = int(port)
        else:
            self.port = 80 if self.scheme == "http" else 443

        self.path = "/" + path

    def request(self, *, redirect_counter: int = 0) -> tuple[str, bool]:
        cached = get_cached_content(self)

        if cached and (not cached.expires_at or cached.expires_at > time()):
            return cached.content, self.view_source

        if self.scheme == "file":
            return self._read_file(), self.view_source
        if self.scheme == "data":
            return self.content or "", self.view_source

        s = get_socket(self)

        request = crlf(f"GET {self.path} HTTP/1.1")
        request += crlf(f"Host: {self.host}")
        request += crlf("Connection: keep-alive")
        request += crlf(f"User-Agent: {UA}")
        request += crlf()

        s.send(request.encode("utf8"))

        # TODO:
        #   - read Content-Type header to determine the encoding rather
        #     than hardcoding / assuming the encoding is utf8
        response = s.makefile("rb", encoding="utf8", newline=crlf())

        statusline = response.readline().decode()

        version, status, explanation = statusline.split(" ", 2)

        if status not in {"200", "301"}:
            raise NotImplementedError(
                f"Handling '{status}' code is not yet implemented"
            )

        response_headers = {}
        while True:
            line = response.readline().decode()
            if line == crlf():
                break
            header, value = line.split(":", 1)
            response_headers[header.casefold()] = value.strip()

        if status == "301":
            redirect_counter += 1

            if redirect_counter == 10:
                raise RuntimeError("too many redirects")

            location = response_headers.get("location")

            if not location:
                raise ValueError("Location not provided for 301 redirect")

            if location.startswith("/"):
                return URL(self.origin + location).request(
                    redirect_counter=redirect_counter
                )

            return URL(location).request(redirect_counter=redirect_counter)

        assert "content-length" in response_headers

        assert "transfer-encoding" not in response_headers
        assert "content-encoding" not in response_headers

        len_bytes = int(response_headers["content-length"])

        content = response.read(len_bytes).decode()

        cache_control = response_headers.get("cache-control")

        should_cache = True
        cache_age = None
        if cache_control:
            directives = cache_control.split(", ")

            if "no-store" in directives:
                should_cache = False

            unsupported_directives = set(directives) - {"no-store", "max-age"}

            if unsupported_directives:
                logger.warning(
                    "Unsupported Cache-Control directives provided: %s",
                    unsupported_directives,
                )
                should_cache = False

            if "max-age" in directives:
                max_age = next(d for d in directives)
                _, max_age_value = max_age.split("=", 1)
                max_age_value = int(max_age_value)

                if max_age_value == 0:
                    should_cache = False
                else:
                    cache_age = max_age_value

        if should_cache:
            cache_content(self, content, max_age=cache_age)

        return content, self.view_source

    @property
    def origin(self):
        if self.scheme not in {"http", "https"}:
            raise ValueError(".origin not implemented for networked URLs")

        port = f":{self.port}" if self.port != 80 else ""

        return f"{self.scheme}://{self.host}{port}"

    def _read_file(self):
        if not self.path:
            raise ValueError("no path provided")

        path = Path(unquote(self.path))
        content = path.read_text()
        return content

    def _set_defaults(self):
        defaults = {
            name: value
            for name, value in self.__class__.__dict__.items()
            if (
                not name.startswith("__")
                and not callable(value)
                and not isinstance(value, property)
            )
        }

        attrs = [name for name in self.__annotations__ if name not in defaults]

        for attr in attrs:
            setattr(self, attr, None)

        for name, value in defaults.items():
            setattr(self, name, value)


def cache_content(url: URL, content: str, *, max_age: int | None = None):
    cache_key = f"{url.scheme}:{url.host}:{url.port}:{url.path}"

    CONTENT_CACHE[cache_key] = CacheEntry(
        content=content,
        expires_at=(int(time() + max_age) if max_age is not None else None),
    )


def get_cached_content(url: URL) -> CacheEntry | None:
    cache_key = f"{url.scheme}:{url.host}:{url.port}:{url.path}"
    return CONTENT_CACHE.get(cache_key)


def get_socket(url: URL):
    cache_key = f"{url.scheme}:{url.host}:{url.port}"

    cached = PERSISTED_SOCKETS.get(cache_key)

    if cached:
        return cached

    s = socket.socket(
        family=socket.AF_INET,
        type=socket.SOCK_STREAM,
        proto=socket.IPPROTO_TCP,
    )

    if url.scheme == "https":
        ctx = ssl.create_default_context()
        s = ctx.wrap_socket(s, server_hostname=url.host)

    s.connect((url.host, url.port))

    PERSISTED_SOCKETS[cache_key] = s

    return s
