import itertools
import math
import re
import xml.etree.ElementTree as ET

TOKEN = re.compile(r"[MLCQZ]|-?\d+(?:\.\d+)?(?:e-?\d+)?")
TRANSLATE = re.compile(r"translate\(\s*(-?[\d.]+)[ ,]+(-?[\d.]+)\s*\)")
ENDPOINT_RADIUS_PX = 30.0
NODE_MARGIN_PX = 28.0
LABEL_SLACK_PX = 2.0


def local(tag):
    return tag.rsplit("}", maxsplit=1)[-1]


def offset_of(element):
    match = TRANSLATE.search(element.get("transform", default=""))
    return (float(match.group(1)), float(match.group(2))) if match else (0.0, 0.0)


def walk(element, origin=(0.0, 0.0)):
    dx, dy = offset_of(element)
    here = (origin[0] + dx, origin[1] + dy)
    yield element, here
    for child in element:
        yield from walk(child, origin=here)


def polyline(d, origin):
    points, command, numbers = [], None, []

    def flush():
        if command in ("M", "L"):
            points.extend((numbers[i], numbers[i + 1]) for i in range(0, len(numbers) - 1, 2))
        elif command == "Q":
            for i in range(0, len(numbers) - 3, 4):
                p0, c, p2 = points[-1], (numbers[i], numbers[i + 1]), (numbers[i + 2], numbers[i + 3])
                for step in range(1, 9):
                    t = step / 8
                    points.append(tuple((1 - t) ** 2 * p0[k] + 2 * (1 - t) * t * c[k] + t * t * p2[k] for k in (0, 1)))
        elif command == "C":
            for i in range(0, len(numbers) - 5, 6):
                p0 = points[-1]
                c1, c2, p3 = (numbers[i], numbers[i + 1]), (numbers[i + 2], numbers[i + 3]), (numbers[i + 4], numbers[i + 5])
                for step in range(1, 9):
                    t, u = step / 8, 1 - step / 8
                    points.append(tuple(u**3 * p0[k] + 3 * u * u * t * c1[k] + 3 * u * t * t * c2[k] + t**3 * p3[k] for k in (0, 1)))

    for token in TOKEN.findall(d):
        if token in "MLCQZ":
            flush()
            command, numbers = token, []
        else:
            numbers.append(float(token))
    flush()
    return [(x + origin[0], y + origin[1]) for x, y in points]


def labelled_child(element):
    label = next((c for c in element if local(c.tag) == "g" and "label" in c.get("class", default="").split()), None)
    box = next((c for c in label.iter() if local(c.tag) == "foreignObject"), None) if label is not None else None
    return label, box


def node_box(node, origin):
    label, box = labelled_child(node)
    if box is None:
        raise ValueError(f"node {node.get('id')} has no label box")
    lx, ly = offset_of(label)
    x0, y0 = origin[0] + lx - NODE_MARGIN_PX, origin[1] + ly - NODE_MARGIN_PX
    return (x0, y0, x0 + float(box.get("width")) + 2 * NODE_MARGIN_PX, y0 + float(box.get("height")) + 2 * NODE_MARGIN_PX)


def edge_label_box(edge_label, origin):
    label, box = labelled_child(edge_label)
    if box is None or float(box.get("width", default="0")) == 0:
        return None, None
    lx, ly = offset_of(label)
    x0, y0 = origin[0] + lx, origin[1] + ly
    return label.get("data-id"), (x0, y0, x0 + float(box.get("width")), y0 + float(box.get("height")))


def edge_name(edge_id, nodes):
    body = re.sub(r"_\d+$", repl="", string=re.sub(r"^L_", repl="", string=edge_id))
    splits = [(body[:i], body[i + 1 :]) for i in range(1, len(body)) if body[i] == "_" and body[:i] in nodes and body[i + 1 :] in nodes]
    if not splits:
        raise ValueError(f"edge {edge_id} does not join two nodes; edges to a subgraph and custom edge ids (e1@-->) are not supported")
    if len(splits) > 1:
        raise ValueError(f"edge {edge_id} has {len(splits)} possible endpoint pairs; rename nodes so the underscore split is unique")
    return splits[0]


def read_svg(source):
    try:
        root = ET.parse(source).getroot()
    except ET.ParseError as error:
        raise ValueError(f"not a readable SVG: {error}") from None
    nodes, raw_edges, raw_labels = {}, [], []
    for element, origin in walk(root):
        cls = element.get("class", default="")
        if local(element.tag) == "g" and cls.split()[:1] == ["node"]:
            name = re.sub(r"-\d+$", repl="", string=element.get("id", default="").split("flowchart-", maxsplit=1)[-1])
            nodes[name] = node_box(element, origin=origin)
        elif local(element.tag) == "path" and "flowchart-link" in cls:
            raw_edges.append((element.get("data-id") or element.get("id", default="").split("-", maxsplit=2)[-1], polyline(element.get("d", default=""), origin=origin)))
        elif local(element.tag) == "g" and cls.split()[:1] == ["edgeLabel"]:
            edge_id, box = edge_label_box(element, origin=origin)
            if box is not None:
                raw_labels.append((edge_id, box))
    edges = [(edge_name(edge_id, nodes=nodes), points) for edge_id, points in raw_edges]
    labels = [(edge_name(edge_id, nodes=nodes), box) for edge_id, box in raw_labels]
    return nodes, edges, labels


def shrink(box, by):
    return (box[0] + by, box[1] + by, box[2] - by, box[3] - by)


def boxes_overlap(a, b):
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def crosses(a, b, c, d):
    def orient(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    return orient(a, b, c) * orient(a, b, d) < 0 and orient(c, d, a) * orient(c, d, b) < 0


def segment_hits_box(a, b, box):
    t0, t1 = 0.0, 1.0
    dx, dy = b[0] - a[0], b[1] - a[1]
    for p, q in ((-dx, a[0] - box[0]), (dx, box[2] - a[0]), (-dy, a[1] - box[1]), (dy, box[3] - a[1])):
        if p == 0:
            if q <= 0:
                return False
        elif p < 0:
            t0 = max(t0, q / p)
        else:
            t1 = min(t1, q / p)
    return t0 < t1


def away_from_ends(points):
    start, end = points[0], points[-1]
    return [p for p in points if math.dist(p, start) > ENDPOINT_RADIUS_PX and math.dist(p, end) > ENDPOINT_RADIUS_PX]


def paths_cross(p1, p2):
    return any(crosses(a, b, c, d) for a, b in zip(p1, p1[1:]) for c, d in zip(p2, p2[1:]))


def label_collisions(nodes, edges, labels):
    on_labels = [
        f"label of {'->'.join(e1)} on label of {'->'.join(e2)}"
        for (e1, b1), (e2, b2) in itertools.combinations(labels, r=2)
        if boxes_overlap(shrink(b1, by=LABEL_SLACK_PX), shrink(b2, by=LABEL_SLACK_PX))
    ]
    on_nodes = [
        f"label of {'->'.join(e)} on {n}"
        for e, box in labels
        for n, node in nodes.items()
        if boxes_overlap(shrink(box, by=LABEL_SLACK_PX), shrink(node, by=NODE_MARGIN_PX))
    ]
    through = [
        f"{'->'.join(e)} through label of {'->'.join(owner)}"
        for owner, box in labels
        for e, p in edges
        if e != owner and any(segment_hits_box(a, b, shrink(box, by=LABEL_SLACK_PX)) for a, b in zip(p, p[1:]))
    ]
    return on_labels + on_nodes + through


def defects(source):
    nodes, edges, labels = read_svg(source)
    if not edges:
        raise ValueError("the diagram has no flowchart edges")
    crossings = [
        f"{'->'.join(e1)} x {'->'.join(e2)}"
        for (e1, p1), (e2, p2) in itertools.combinations(edges, r=2)
        if (paths_cross(away_from_ends(p1), away_from_ends(p2)) if set(e1) & set(e2) else paths_cross(p1, p2))
    ]
    hidden = [
        f"{'->'.join(e)} under {n}"
        for e, p in edges
        for n, box in nodes.items()
        if n not in e and any(segment_hits_box(a, b, box) for a, b in zip(p, p[1:]))
    ]
    return {"nodes": len(nodes), "edges": len(edges), "crossings": crossings, "under_nodes": hidden, "label_collisions": label_collisions(nodes, edges=edges, labels=labels)}


def problems(found):
    return found["crossings"] + found["under_nodes"] + found["label_collisions"]
