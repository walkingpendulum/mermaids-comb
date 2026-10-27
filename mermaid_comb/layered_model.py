import itertools
from collections import defaultdict
from dataclasses import dataclass

from ortools.sat.python import cp_model

BORDER_SIDES = {"borderLeft": "left", "borderRight": "right"}


@dataclass(frozen=True)
class Segment:
    tail: str
    head: str
    owner: str
    is_border: bool


class LayeredGraph:
    def __init__(self, layout, ignore=frozenset()):
        self.nodes = {n["v"]: n for n in layout["nodes"]}
        self.rank = {v: n["rank"] for v, n in self.nodes.items() if n.get("rank") is not None}
        layers = defaultdict(list)
        for v, r in self.rank.items():
            layers[r].append(v)
        self.layers = [sorted(layers[r], key=lambda v: self.nodes[v]["order"]) for r in range(max(layers) + 1)]
        self.segments = defaultdict(list)
        for tail, head, name in layout["edges"]:
            if self.rank[head] - self.rank[tail] != 1:
                raise ValueError(f"dagre edge {tail}->{head} spans {self.rank[head] - self.rank[tail]} ranks after normalisation")
            owner = self.owner(tail, head, name)
            if owner in ignore:
                continue
            border = self.nodes[tail]["dummy"] == "border" or self.nodes[head]["dummy"] == "border"
            self.segments[self.rank[tail]].append(Segment(tail=tail, head=head, owner=owner, is_border=border))
        self.bounds = defaultdict(dict)
        for v, n in self.nodes.items():
            side = BORDER_SIDES.get(n.get("borderType"))
            if side:
                self.bounds[(n["parent"], self.rank[v])][side] = v

    def owner(self, tail, head, name):
        for v in (head, tail):
            n = self.nodes[v]
            if n["dummy"] == "border":
                return f"border:{n['parent']}"
            if n["edge"]:
                return n["edge"][2] or f"{n['edge'][0]}->{n['edge'][1]}"
        return name or f"{tail}->{head}"

    def is_member(self, v, cluster):
        n = self.nodes[v]
        if n["dummy"] == "border" and BORDER_SIDES.get(n.get("borderType")) and n["parent"] == cluster:
            return False
        parent = n["parent"]
        while parent is not None:
            if parent == cluster:
                return True
            parent = self.nodes[parent]["parent"]
        return False

    def crossings(self, layering):
        position = {v: i for layer in layering for i, v in enumerate(layer)}
        edge_edge, edge_border = set(), 0
        for segments in self.segments.values():
            for a, b in itertools.combinations(segments, r=2):
                if a.tail == b.tail or a.head == b.head or a.is_border and b.is_border:
                    continue
                if (position[a.tail] < position[b.tail]) != (position[a.head] < position[b.head]):
                    if a.is_border or b.is_border:
                        edge_border += 1
                    else:
                        edge_edge.add(tuple(sorted((a.owner, b.owner))))
        return len(edge_edge), edge_border

    def solve(self, max_deterministic_time=60.0):
        model = cp_model.CpModel()
        before = {}
        for layer in self.layers:
            ordered = sorted(layer)
            for a, b in itertools.combinations(ordered, r=2):
                before[(a, b)] = model.new_bool_var(f"b_{a}_{b}")
            for a, b, c in itertools.combinations(ordered, r=3):
                model.add(before[(a, b)] + before[(b, c)] - before[(a, c)] >= 0)
                model.add(before[(a, b)] + before[(b, c)] - before[(a, c)] <= 1)

        def precedes(a, b):
            return before[(a, b)] if a < b else 1 - before[(b, a)]

        for (cluster, r), sides in self.bounds.items():
            left, right = sides["left"], sides["right"]
            model.add(precedes(left, right) == 1)
            for v in self.layers[r]:
                if v in (left, right):
                    continue
                if self.is_member(v, cluster):
                    model.add(precedes(left, v) == 1)
                    model.add(precedes(v, right) == 1)
                else:
                    model.add(precedes(v, left) == precedes(v, right))

        edge_terms, border_terms = [], []
        for segments in self.segments.values():
            for a, b in itertools.combinations(segments, r=2):
                if a.tail == b.tail or a.head == b.head or a.is_border and b.is_border:
                    continue
                crossed = model.new_bool_var(f"x_{a.tail}_{a.head}_{b.tail}_{b.head}")
                model.add(crossed >= precedes(a.tail, b.tail) - precedes(a.head, b.head))
                model.add(crossed >= precedes(a.head, b.head) - precedes(a.tail, b.tail))
                (border_terms if a.is_border or b.is_border else edge_terms).append(crossed)
        model.minimize((len(border_terms) + 1) * sum(edge_terms) + sum(border_terms))
        solver = cp_model.CpSolver()
        solver.parameters.num_workers = 1
        solver.parameters.random_seed = 0
        solver.parameters.max_deterministic_time = max_deterministic_time
        status = solver.solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            raise RuntimeError(f"no ordering of dagre's layered graph: {solver.status_name(status)}")
        layering = [sorted(layer, key=lambda v, layer=layer: -sum(solver.value(precedes(v, w)) for w in layer if w != v)) for layer in self.layers]
        return layering, self.crossings(layering)
