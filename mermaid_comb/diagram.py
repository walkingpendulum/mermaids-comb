import re
from dataclasses import dataclass, field

from . import syntax

NODE_ID = re.compile(r"^\s*([A-Za-z_][\w-]*)")
EDGE = re.compile(
    r"^(?P<indent>\s*)(?P<src>[A-Za-z_][\w-]*)\s*(?P<link>-{2,}>?|={2,}>?|-\.+->?|~{3,})(?P<label>\|[^|]*\|)?\s*(?P<dst>[A-Za-z_][\w-]*)\s*$"
)
HEADER_DIRECTION = re.compile(r"^\s*(?:flowchart|graph)\s+(LR|RL|TB|TD|BT)\b")
DAGRE_LAYOUT = re.compile(r"^\s*layout:\s*dagre\s*$", flags=re.M)


@dataclass
class Edge:
    index: int
    src: str
    dst: str
    kind: str
    head: bool
    length: int
    label: str
    indent: str
    comments: list = field(default_factory=list)

    @property
    def invisible(self):
        return self.kind == "~"

    @property
    def dagre_id(self):
        return f"L_{self.src}_{self.dst}_0"

    def line(self, length, labels):
        if self.kind == "~":
            token = "~" * (length + 2)
        elif self.kind == ".":
            token = "-" + "." * length + "-" + (">" if self.head else "")
        else:
            token = self.kind * (length + 1) + ">" if self.head else self.kind * (length + 2)
        return f"{self.indent}{self.src} {token}{self.label if labels else ''} {self.dst}"


def parse_link(link):
    head = link.endswith(">")
    body = link[:-1] if head else link
    if body.startswith("~"):
        return "~", False, len(body) - 2
    if "." in body:
        return ".", head, body.count(".")
    return body[0], head, len(body) - (1 if head else 2)


class Diagram:
    def __init__(self, text):
        if not DAGRE_LAYOUT.search(text):
            raise ValueError("the front matter must pin `layout: dagre`; the solver models dagre only")
        self.text = text
        self.header, self.root, self.styles, edge_count = syntax.parse(text)
        self.edges, self.nodes, self.parent = [], {}, {}
        self.index_tree(self.root, group_id=None)
        if len(self.edges) != edge_count:
            raise ValueError(f"parsed {len(self.edges)} edges, expected {edge_count}")
        self.edges.sort(key=lambda e: e.index)
        for edge in self.edges:
            for end in (edge.src, edge.dst):
                if end in self.parent and end not in self.nodes:
                    raise ValueError(f"edge {edge.src} -> {edge.dst} points at subgraph {end}; edges to a subgraph are not supported")
                if end not in self.nodes:
                    raise ValueError(f"node {end} is used by an edge but never declared; declare it on its own line")
        ids = [e.dagre_id for e in self.edges]
        if len(set(ids)) != len(ids):
            raise ValueError("parallel edges between the same two nodes are not supported")
        directions = [m.group(1) for m in map(HEADER_DIRECTION.match, self.header) if m]
        if not directions:
            raise ValueError("the flowchart header has no direction")
        self.direction = directions[0]

    def index_tree(self, group, group_id):
        for item in group["items"] + group["edges"]:
            if "items" in item:
                subgraph_id = NODE_ID.match(item["head"][-1].split("subgraph", maxsplit=1)[1]).group(1)
                if group_id is not None:
                    raise ValueError(f"nested subgraph {subgraph_id} is not supported")
                self.parent[subgraph_id] = group_id
                self.index_tree(item, group_id=subgraph_id)
            elif item["edge"] is not None:
                *comments, statement = item["lines"]
                match = EDGE.match(statement)
                if not match:
                    raise ValueError(f"unsupported edge form (use 'A -->|label| B'): {statement.strip()}")
                kind, head, length = parse_link(match.group("link"))
                item["edge_obj"] = Edge(
                    index=item["edge"],
                    src=match.group("src"),
                    dst=match.group("dst"),
                    kind=kind,
                    head=head,
                    length=length,
                    label=match.group("label") or "",
                    indent=match.group("indent"),
                    comments=comments,
                )
                self.edges.append(item["edge_obj"])
            else:
                node_id = NODE_ID.match(item["lines"][-1]).group(1)
                item["id"] = node_id
                self.nodes[node_id] = item
                self.parent[node_id] = group_id

    def groups(self):
        members = {}
        for node in self.nodes:
            if self.parent[node] is not None:
                members.setdefault(self.parent[node], set()).add(node)
        return {g: frozenset(m) for g, m in sorted(members.items())}

    def emit(self, node_order=None, edge_order=None, lengths=None, labels=True, extra_lines=()):
        node_rank = {v: i for i, v in enumerate(node_order or [])}
        edge_rank = {e: i for i, e in enumerate(edge_order or [])}
        lengths = lengths or {}
        order = []

        def is_group(item):
            return "items" in item

        def is_edge(item):
            return not is_group(item) and item["edge"] is not None

        def node_key(item):
            if is_group(item):
                keys = [node_key(child) for child in item["items"] if not is_edge(child)]
                return min(keys) if keys else float("inf")
            return node_rank.get(item["id"], float("inf"))

        def edge_lines(items):
            out = []
            for item in sorted(items, key=lambda i: (edge_rank.get(i["edge"], float("inf")), i["edge"])):
                edge = item["edge_obj"]
                order.append(edge.index)
                out += edge.comments + [edge.line(lengths.get(edge.index, edge.length), labels=labels)]
            return out

        def walk(group):
            out = group["head"] + group["fixed"]
            for item in sorted((i for i in group["items"] if not is_edge(i)), key=node_key):
                out += walk(item) if is_group(item) else item["lines"]
            return out + edge_lines([i for i in group["items"] + group["edges"] if is_edge(i)]) + group["tail"]

        body = walk(self.root) + list(extra_lines)
        new_index = {old: new for new, old in enumerate(order)}
        styles = [syntax.restyle(line, new_index=new_index, edge_count=len(self.edges)) for line in self.styles]
        return "\n".join([*self.header, *body, *styles]) + "\n"
