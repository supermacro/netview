import socket
import ssl
from pathlib import Path
from urllib.parse import unquote

UA = "NetView/0.1"


PERSISTED_SOCKETS = {}


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

    def request(self) -> tuple[str, bool]:
        if self.content:
            return self.content, self.view_source

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

        if int(status) != 200:
            raise NotImplementedError("Handling non 200 codes is not yet implemented")

        response_headers = {}
        while True:
            line = response.readline().decode()
            if line == crlf():
                break
            header, value = line.split(":", 1)
            response_headers[header.casefold()] = value.strip()

        assert "content-length" in response_headers

        assert "transfer-encoding" not in response_headers
        assert "content-encoding" not in response_headers

        len_bytes = int(response_headers["content-length"])

        content = response.read(len_bytes).decode()

        self.content = content

        return content, self.view_source

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
            if (not name.startswith("__") and not callable(value))
        }

        attrs = [name for name in self.__annotations__ if name not in defaults]

        for attr in attrs:
            setattr(self, attr, None)

        for name, value in defaults.items():
            setattr(self, name, value)


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
