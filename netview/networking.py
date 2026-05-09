import socket
import ssl
from pathlib import Path
from urllib.parse import unquote

UA = "NetView/0.1"


def crlf(s=""):
    return s + "\r\n"


class URL:
    def __init__(self, url: str):
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

    def request(self):
        if self.content:
            return self.content

        if self.scheme == "file":
            return self._read_file()
        if self.scheme == "data":
            return self.content

        s = socket.socket(
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
        if self.scheme == "https":
            ctx = ssl.create_default_context()
            s = ctx.wrap_socket(s, server_hostname=self.host)

        s.connect((self.host, self.port))

        request = crlf(f"GET {self.path} HTTP/1.1")
        request += crlf(f"Host: {self.host}")
        request += crlf("Connection: close")
        request += crlf(f"User-Agent: {UA}")
        request += crlf()

        s.send(request.encode("utf8"))

        # TODO:
        #   - read Content-Type header to determine the encoding rather
        #     than hardcoding / assuming the encoding is utf8
        response = s.makefile("r", encoding="utf8", newline=crlf())

        statusline = response.readline()

        version, status, explanation = statusline.split(" ", 2)

        if int(status) != 200:
            raise NotImplementedError("Handling non 200 codes is not yet implemented")

        response_headers = {}
        while True:
            line = response.readline()
            if line == crlf():
                break
            header, value = line.split(":", 1)
            response_headers[header.casefold()] = value.strip()

        assert "transfer-encoding" not in response_headers
        assert "content-encoding" not in response_headers

        content = response.read()

        self.content = content

        s.close()

        return content

    def _read_file(self):
        if not self.path:
            raise ValueError("no path provided")

        path = Path(unquote(self.path))
        content = path.read_text()
        return content
