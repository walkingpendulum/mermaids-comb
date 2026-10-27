import re

LINK_TOKEN = re.compile(r"<?[-=.~]{2,}[>ox]?")
LABEL_TEXT = re.compile(r'"[^"]*"|\|[^|]*\|')
NODE_TEXT = re.compile(r"\[[^\]]*\]|\([^)]*\)|\{[^}]*\}")
KEYWORD = re.compile(r"\s*(subgraph|end|direction|classDef|class|click|style|linkStyle)\b")
STYLING = {"classDef", "class", "click", "style", "linkStyle"}
LINK_STYLE = re.compile(r"^(\s*linkStyle\s+)([\d\s,]+?|default)(\s+\S.*)$")
DIAGRAM_HEADER = re.compile(r"\s*(flowchart|graph)\b(?!:)")


def arrow_count(line):
    bare = NODE_TEXT.sub(repl="", string=LABEL_TEXT.sub(repl="", string=line))
    if "&" in bare:
        raise ValueError(f"'&' edge groups are not supported; split into one edge per line: {line.strip()}")
    count = sum(1 for token in LINK_TOKEN.findall(bare) if len(token.lstrip("<")) >= 3)
    if count > 1:
        raise ValueError(f"chained edges are not supported; split into one edge per line: {line.strip()}")
    return count


def new_group(head):
    return {"head": head, "fixed": [], "items": [], "edges": [], "tail": []}


def statements(lines):
    joined, open_text = [], None
    for line in lines:
        open_text = line if open_text is None else f"{open_text}\n{line}"
        if open_text.count("`") % 2 == 0:
            joined.append(open_text)
            open_text = None
    if open_text is not None:
        raise ValueError(f"unclosed backtick string: {open_text.splitlines()[0].strip()}")
    return joined


def parse(text):
    lines = text.splitlines()
    front_end = -1
    if lines and lines[0].strip() == "---":
        front_end = next((i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---"), None)
        if front_end is None:
            raise ValueError("front matter has no closing ---")
    start = next((i for i, line in enumerate(lines) if i > front_end and DIAGRAM_HEADER.match(line)), None)
    if start is None:
        raise ValueError("no flowchart or graph header line")
    root, styles, pending, edge_count = new_group([]), [], [], 0
    stack = [root]
    for line in statements(lines[start + 1 :]):
        if not line.strip():
            continue
        if line.strip().startswith("%%"):
            pending.append(line)
            continue
        match = KEYWORD.match(line)
        keyword = match.group(1) if match else None
        if keyword in STYLING:
            styles += pending + [line]
        elif keyword == "subgraph":
            group = new_group(pending + [line])
            stack[-1]["items"].append(group)
            stack.append(group)
        elif keyword == "end":
            if len(stack) == 1:
                raise ValueError("'end' without a matching subgraph")
            stack.pop()["tail"] = pending + [line]
        elif keyword == "direction":
            stack[-1]["fixed"] += pending + [line]
        else:
            is_edge = arrow_count(line) == 1
            item = {"lines": pending + [line], "edge": edge_count if is_edge else None}
            edge_count += is_edge
            (root["edges"] if is_edge and len(stack) == 1 else stack[-1]["items"]).append(item)
        pending = []
    if len(stack) != 1:
        raise ValueError("subgraph without a matching 'end'")
    return lines[: start + 1], root, styles + pending, edge_count


def restyle(line, new_index, edge_count):
    match = LINK_STYLE.match(line)
    if not match or match.group(2) == "default":
        return line
    indices = [int(x) for x in re.split(r"\s*,\s*", string=match.group(2).strip())]
    if any(i >= edge_count for i in indices):
        raise ValueError(f"linkStyle refers to an edge that does not exist: {line.strip()}")
    return f"{match.group(1)}{','.join(str(new_index[i]) for i in indices)}{match.group(3)}"
