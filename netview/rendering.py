import re


def show(body: str) -> str:
    in_tag = False

    raw_content = ""

    for c in body:
        if c == "<":
            in_tag = True
        elif c == ">":
            in_tag = False
        elif not in_tag:
            raw_content += c

    return raw_content


NAMED_CHARACTER_REFERENCES_MAPPING = {
    "lt": "<",
    "gt": ">",
    "amp": "&",
    "quot": '"',
}


def render(body: str) -> str:
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


if __name__ == "__main__":
    html = "<body>hello, &lt;div&gt;</body>"
    print(f"HTML: {html}")

    result = render(html)
    assert result == "hello, <div>"

    print(result)
