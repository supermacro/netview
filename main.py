import logging
import sys
import tkinter

from netview.networking import URL
from netview.rendering import Browser

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    url = sys.argv[1]

    if not url:
        raise RuntimeError("Must supply url")

    Browser().load(URL(url))

    tkinter.mainloop()
