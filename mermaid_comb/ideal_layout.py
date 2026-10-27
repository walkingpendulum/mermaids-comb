import itertools
from dataclasses import dataclass

from ortools.sat.python import cp_model

TIME_LIMIT = 60.0


@dataclass(frozen=True)
class Problem:
    nodes: tuple
    edges: tuple
    groups: dict

    @classmethod
    def from_diagram(cls, diagram):
        return cls(
            nodes=tuple(diagram.nodes),
            edges=tuple((e.src, e.dst) for e in diagram.edges if not e.invisible),
            groups=diagram.groups(),
        )

    def group_of(self, v):
        return next((g for g, members in self.groups.items() if v in members), None)

    def depths(self):
        depth = {v: 0 for v in self.nodes}
        height = {v: 0 for v in self.nodes}
        for _ in self.nodes:
            for u, v in self.edges:
                depth[v] = max(depth[v], depth[u] + 1)
                height[u] = max(height[u], height[v] + 1)
        if any(depth[v] <= depth[u] for u, v in self.edges):
            raise ValueError("the flowchart has a cycle; the solver handles acyclic diagrams only")
        return depth, height


def membership(problem, o, g):
    members = problem.groups[g]
    if not o.startswith("edge"):
        return o in members
    u, v = problem.edges[int(o[4:])]
    if u in members:
        return True
    if v not in members:
        return False
    source_group = problem.group_of(u)
    return True if source_group is None else source_group


class LayeredDrawing:
    def __init__(self, problem, slack_ranks):
        self.problem = problem
        depth, height = problem.depths()
        top = 2 * (max(depth.values()) + slack_ranks) + 1
        self.windows = {v: list(range(2 * depth[v] + 1, top - 2 * height[v] + 1, 2)) for v in problem.nodes}
        self.ranks = range(top + 2)
        self.model = cp_model.CpModel()
        self.present, self.compared = {}, {}
        self.add_ranks()
        self.add_edges()
        self.add_groups()
        self.add_positions()
        self.add_containment()
        self.add_chains()
        self.add_crossings()

    def add_ranks(self):
        self.rank = {}
        for v in self.problem.nodes:
            for t in self.windows[v]:
                self.present[(v, t)] = self.model.new_bool_var(f"on_{v}_{t}")
            self.model.add_exactly_one(self.present[(v, t)] for t in self.windows[v])
            self.rank[v] = self.model.new_int_var_from_domain(cp_model.Domain.from_values(self.windows[v]), name=f"r_{v}")
            self.model.add(self.rank[v] == sum(t * self.present[(v, t)] for t in self.windows[v]))
        self.model.add_bool_or(self.present[(v, 1)] for v in self.problem.nodes if (v, 1) in self.present)

    def compare(self, v, t, sense):
        if (v, t, sense) not in self.compared:
            b = self.model.new_bool_var(f"{sense}_{v}_{t}")
            if sense == "before":
                self.model.add(self.rank[v] < t).only_enforce_if(b)
                self.model.add(self.rank[v] >= t).only_enforce_if(~b)
            else:
                self.model.add(self.rank[v] > t).only_enforce_if(b)
                self.model.add(self.rank[v] <= t).only_enforce_if(~b)
            self.compared[(v, t, sense)] = b
        return self.compared[(v, t, sense)]

    def add_edges(self):
        self.span, self.point_window = [], {}
        for i, (u, v) in enumerate(self.problem.edges):
            self.model.add(self.rank[v] >= self.rank[u] + 2)
            self.span.append(self.rank[v] - self.rank[u])
            self.point_window[i] = range(min(self.windows[u]), max(self.windows[v]) + 1)
            for t in range(min(self.windows[u]) + 1, max(self.windows[v])):
                inside = self.model.new_bool_var(f"inside_{i}_{t}")
                self.model.add_bool_and([self.compare(u, t, "before"), self.compare(v, t, "after")]).only_enforce_if(inside)
                self.model.add_bool_or([~self.compare(u, t, "before"), ~self.compare(v, t, "after")]).only_enforce_if(~inside)
                self.present[(f"edge{i}", t)] = inside

    def add_groups(self):
        self.border_range, self.past_group, self.group_window = {}, {}, {}
        for g, members in self.problem.groups.items():
            first = self.model.new_int_var(0, ub=len(self.ranks) - 1, name=f"first_{g}")
            last = self.model.new_int_var(0, ub=len(self.ranks) - 1, name=f"last_{g}")
            self.model.add_min_equality(first, [self.rank[m] for m in members])
            self.model.add_max_equality(last, [self.rank[m] for m in members])
            self.group_window[g] = range(min(min(self.windows[m]) for m in members) - 1, max(max(self.windows[m]) for m in members) + 2)
            for t in self.ranks:
                in_range = self.model.new_bool_var(f"range_{g}_{t}")
                self.model.add(first - 1 <= t).only_enforce_if(in_range)
                self.model.add(last + 1 >= t).only_enforce_if(in_range)
                above = self.model.new_bool_var(f"above_{g}_{t}")
                self.model.add(first - 1 > t).only_enforce_if(above)
                below = self.model.new_bool_var(f"below_{g}_{t}")
                self.model.add(last + 1 < t).only_enforce_if(below)
                self.model.add_exactly_one([in_range, above, below])
                self.past_group[(g, t)] = below
                if t in self.group_window[g]:
                    self.border_range[(g, t)] = in_range
                    self.present[(f"left:{g}", t)] = in_range
                    self.present[(f"right:{g}", t)] = in_range
                else:
                    self.model.add(in_range == 0)

    def add_positions(self):
        self.objects_at = {t: [o for (o, s) in self.present if s == t] for t in self.ranks}
        self.x = {}
        for t in self.ranks:
            capacity = len(self.objects_at[t])
            for k, o in enumerate(self.objects_at[t]):
                self.x[(o, t)] = self.model.new_int_var(0, ub=2 * capacity, name=f"x_{o}_{t}")
                self.model.add(self.x[(o, t)] < capacity).only_enforce_if(self.present[(o, t)])
                self.model.add(self.x[(o, t)] == capacity + k).only_enforce_if(~self.present[(o, t)])
            if self.objects_at[t]:
                self.model.add_all_different([self.x[(o, t)] for o in self.objects_at[t]])

    def add_containment(self):
        for g in self.problem.groups:
            for t in self.group_window[g]:
                left, right = self.x[(f"left:{g}", t)], self.x[(f"right:{g}", t)]
                self.model.add(left < right).only_enforce_if(self.border_range[(g, t)])
                for o in self.objects_at[t]:
                    if o not in (f"left:{g}", f"right:{g}"):
                        self.contain(o, g, t, left=left, right=right)

    def contain(self, o, g, t, left, right):
        x, rule = self.x[(o, t)], membership(self.problem, o, g)
        inside_when = [self.present[(o, t)], self.border_range[(g, t)]]
        if rule is True:
            self.model.add(x > left).only_enforce_if(inside_when)
            self.model.add(x < right).only_enforce_if(inside_when)
            return
        outside_when = list(inside_when)
        if rule is not False:
            self.model.add(x > left).only_enforce_if(inside_when + [self.past_group[(rule, t)]])
            self.model.add(x < right).only_enforce_if(inside_when + [self.past_group[(rule, t)]])
            outside_when.append(~self.past_group[(rule, t)])
        outside_left = self.model.new_bool_var(f"ol_{o}_{g}_{t}")
        self.model.add(x < left).only_enforce_if(outside_when + [outside_left])
        self.model.add(x > right).only_enforce_if(outside_when + [~outside_left])

    def add_chains(self):
        self.point, self.has_point, self.chains = {}, {}, []
        for i, (u, v) in enumerate(self.problem.edges):
            for t in self.point_window[i]:
                sources = [(self.present[(obj, t)], obj) for obj in (u, v, f"edge{i}") if (obj, t) in self.present]
                p = self.model.new_int_var(0, ub=2 * len(self.objects_at[t]), name=f"p_{i}_{t}")
                exists = self.model.new_bool_var(f"pt_{i}_{t}")
                for lit, obj in sources:
                    self.model.add(p == self.x[(obj, t)]).only_enforce_if(lit)
                self.model.add_exactly_one([lit for lit, _ in sources] + [~exists])
                self.point[(f"e{i}", t)], self.has_point[(f"e{i}", t)] = p, exists
            self.chains.append((f"e{i}", "edge"))
        for g in self.problem.groups:
            for side in ("left", "right"):
                name = f"{side}:{g}"
                for t in self.group_window[g]:
                    self.point[(name, t)], self.has_point[(name, t)] = self.x[(name, t)], self.border_range[(g, t)]
                self.chains.append((name, "border"))

    def add_crossings(self):
        self.edge_crossings, self.border_crossings = [], []
        for (a, kind_a), (b, kind_b) in itertools.combinations(self.chains, r=2):
            if kind_a == kind_b == "border":
                continue
            for t in self.ranks[:-1]:
                if all(key in self.point for key in ((a, t), (b, t), (a, t + 1), (b, t + 1))):
                    crossed = self.crossing(a, b, t)
                    (self.edge_crossings if kind_a == kind_b == "edge" else self.border_crossings).append(crossed)
        border_weight = len(self.problem.edges) * len(self.ranks) + 1
        edge_weight = border_weight * (len(self.border_crossings) + 1)
        self.model.minimize(edge_weight * sum(self.edge_crossings) + border_weight * sum(self.border_crossings) + sum(self.span))

    def crossing(self, a, b, t):
        live = [self.has_point[(a, t)], self.has_point[(b, t)], self.has_point[(a, t + 1)], self.has_point[(b, t + 1)]]
        crossed = self.model.new_bool_var(f"c_{a}_{b}_{t}")
        for first, second in ((a, b), (b, a)):
            lead = self.model.new_bool_var(f"lead_{first}_{second}_{t}")
            self.model.add(self.point[(first, t)] < self.point[(second, t)]).only_enforce_if(lead)
            self.model.add(self.point[(first, t)] >= self.point[(second, t)]).only_enforce_if(~lead)
            swap = self.model.new_bool_var(f"swap_{first}_{second}_{t}")
            self.model.add(self.point[(first, t + 1)] > self.point[(second, t + 1)]).only_enforce_if(swap)
            self.model.add(self.point[(first, t + 1)] <= self.point[(second, t + 1)]).only_enforce_if(~swap)
            self.model.add_bool_or([~lead, ~swap, *[~l for l in live], crossed])
        return crossed


def optimal_layering(problem, slack_ranks):
    drawing = LayeredDrawing(problem, slack_ranks=slack_ranks)
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 1
    solver.parameters.random_seed = 0
    solver.parameters.max_deterministic_time = TIME_LIMIT
    status = solver.solve(drawing.model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(f"no layout found: {solver.status_name(status)}")
    return {
        "proven": status == cp_model.OPTIMAL,
        "slack": slack_ranks,
        "edge_crossings": sum(solver.value(c) for c in drawing.edge_crossings),
        "border_crossings": sum(solver.value(c) for c in drawing.border_crossings),
        "ranks": {v: solver.value(drawing.rank[v]) for v in problem.nodes},
        "layering": [sorted((o for o in drawing.objects_at[t] if solver.value(drawing.present[(o, t)])), key=lambda o, t=t: solver.value(drawing.x[(o, t)])) for t in drawing.ranks],
    }
