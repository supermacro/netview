import logging
import re
import tkinter
from enum import StrEnum

from netview.networking import URL
from netview.performance import performance_budget

logger = logging.getLogger(__name__)


class ScrollType(StrEnum):
    ARROW_UP = "arrow_up"
    ARROW_DOWN = "arrow_down"
    MOUSEWHEEL = "mousewheel"


NAMED_CHARACTER_REFERENCES_MAPPING = {
    "lt": "<",
    "gt": ">",
    "amp": "&",
    "quot": '"',
    "copy": "©",
    "ndash": "–",
}


def decode(body: str, cursor: int) -> tuple[str, int]:
    char = body[cursor]

    if char == "&":
        substr = body[cursor:]

        named_char_ref_match = re.match(r"&(\w+);", substr)

        if named_char_ref_match:
            ref = named_char_ref_match.group(1)
            decoded = NAMED_CHARACTER_REFERENCES_MAPPING[ref]

            if not decoded:
                raise ValueError(f"Unknown character ref: {ref}")

            # must add 2 to account for "&" and ";"
            skip = cursor + len(ref) + 2

            return decoded, skip

    return char, cursor + 1


SCROLL_STEP = 100
WIDTH, HEIGHT = 800, 600
HSTEP, VSTEP = 13, 18


class Browser:
    def __init__(self):
        self.window = tkinter.Tk()
        self.canvas = tkinter.Canvas(
            self.window,
            width=WIDTH,
            height=HEIGHT,
        )

        self.canvas.pack()
        self.scroll = 0

        self.window.bind("<Up>", lambda e: self.handle_scroll(e, ScrollType.ARROW_UP))
        self.window.bind(
            "<Down>", lambda e: self.handle_scroll(e, ScrollType.ARROW_DOWN)
        )
        self.window.bind(
            "<MouseWheel>", lambda e: self.handle_scroll(e, ScrollType.MOUSEWHEEL)
        )

    @performance_budget(budget_ms=17)
    def draw(self):
        """
        Works at the screen level
        """

        # ensure we clear current frame before
        # we redraw again
        self.canvas.delete("all")

        for x, y, c in self.display_list:
            if y > self.scroll + HEIGHT:
                continue
            if y + VSTEP < self.scroll:
                continue

            self.canvas.create_text(x, y - self.scroll, text=c)

    def load(self, url: URL):
        html_content, view_source = url.request()
        text = lex(html_content)
        self.display_list = layout(text)
        self.draw()

    def handle_scroll(self, e: tkinter.Event, scroll_type: ScrollType):
        cursor_x, last_y, c = self.display_list[-1]

        prev_scroll = self.scroll

        if scroll_type == ScrollType.ARROW_DOWN or (
            scroll_type == ScrollType.MOUSEWHEEL and e.delta < 0
        ):
            if self.scroll < last_y:
                self.scroll += SCROLL_STEP
        elif scroll_type == ScrollType.ARROW_UP or (
            scroll_type == ScrollType.MOUSEWHEEL and e.delta > 0
        ):
            if self.scroll > SCROLL_STEP:
                self.scroll -= SCROLL_STEP
        else:
            raise ValueError(f"unrecognized scroll type: {scroll_type}")

        # avoid unnecessary redraw
        if prev_scroll == self.scroll:
            return

        self.draw()


def lex(body: str) -> str:
    cursor = 0
    content = ""
    in_tag = False

    while cursor < len(body):
        char = body[cursor]

        if char == "<":
            in_tag = True
            cursor += 1
        elif char == ">":
            in_tag = False
            cursor += 1
        elif in_tag:
            # do nothing with metadata
            # drop html tag metadata for now
            cursor += 1
        elif not in_tag:
            decoded_content, next_cursor = decode(body, cursor)
            content += decoded_content
            cursor = next_cursor

    return content


def layout(text) -> list[tuple[int, int, str]]:
    """
    Works at the page level. Concerns with laying out
    content entirely, irrespective of screen position.
    """
    display_list = []
    cursor_x, cursor_y = HSTEP, VSTEP
    for c in text:
        if c == "\n":
            cursor_y += VSTEP * 1.2
            cursor_x = HSTEP
            continue

        display_list.append((cursor_x, cursor_y, c))
        cursor_x += HSTEP

        if cursor_x >= WIDTH - HSTEP:
            cursor_y += VSTEP
            cursor_x = HSTEP

    return display_list
