from collections import Counter


def stripped(lines):
    return tuple(line.strip() for line in lines)


def group_lines(group, group_id=None):
    found = {group_id: (stripped(group["head"]), stripped(group["fixed"]), stripped(group["tail"]))}
    for item in group["items"]:
        if "items" in item:
            found.update(group_lines(item, group_id=item["head"][-1].strip()))
    return found


def signature(diagram):
    return {
        "nodes": {v: stripped(item["lines"]) for v, item in diagram.nodes.items()},
        "groups": dict(diagram.parent),
        "group_lines": group_lines(diagram.root),
        "edges": Counter((e.src, e.dst, e.kind, e.head, e.label) for e in diagram.edges if not e.invisible),
        "styles": sorted(diagram.styles),
        "header": list(diagram.header),
    }


def invisible_lines(diagram):
    return Counter((e.src, e.dst, e.length) for e in diagram.edges if e.invisible)


def differences(original, solved):
    a, b = signature(original), signature(solved)
    changed = [key for key in a if a[key] != b[key]]
    kept, found = invisible_lines(original), invisible_lines(solved)
    if kept - found:
        changed.append("invisible edges of the input")
    added = found - kept
    uncommented = [f"{e.src} ~~~ {e.dst}" for e in solved.edges if e.invisible and added[(e.src, e.dst, e.length)] and not any(c.strip().startswith("%%") for c in e.comments)]
    return changed + [f"added invisible edge without a %% comment: {line}" for line in uncommented]
