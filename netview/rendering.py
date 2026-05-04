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
