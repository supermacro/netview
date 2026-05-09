import sys

from netview.networking import URL
from netview.rendering import render


def load(url: URL):
    body, view_source = url.request()

    if view_source:
        print(body)
    else:
        print(render(body))


if __name__ == "__main__":
    print("> Beginning request")

    DEFAULT_URL = "http://info.cern.ch/hypertext/WWW/TheProject.html"

    if len(sys.argv) < 2:
        print(f"No url provided, defaulting to {DEFAULT_URL}")
        url = DEFAULT_URL
    else:
        url = sys.argv[1]

    load(URL(url))
