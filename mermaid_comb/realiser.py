from .diagram import Diagram
from .layered_model import LayeredGraph


def inversions(layering, target):
    total = 0
    for layer, goal in zip(layering, target):
        index = {v: i for i, v in enumerate(goal)}
        seq = [index[v] for v in layer]
        total += sum(1 for i in range(len(seq)) for j in range(i + 1, len(seq)) if seq[i] > seq[j])
    return total


def moved(order, i, j):
    rest = order[:i] + order[i + 1 :]
    return rest[:j] + [order[i]] + rest[j:]


def moves(order):
    return (moved(order, i, j) for i in range(len(order)) for j in range(len(order)) if j != i)


class PreGraph:
    def __init__(self, pre, diagram):
        self.pre = pre
        self.real = set(diagram.nodes)
        self.owner = {}
        for node in pre["nodes"]:
            edge_obj = node["value"].get("edgeObj")
            if node["value"].get("dummy") in ("edge", "edge-label") and edge_obj:
                self.owner[node["v"]] = edge_obj.get("name")
        unknown = set(self.owner.values()) - {e.dagre_id for e in diagram.edges}
        if unknown:
            raise ValueError(f"dagre built dummy chains for edges the parser did not see: {sorted(unknown)}")


class Realiser:
    def __init__(self, diagram, lengths, renderer, ignore=frozenset()):
        self.diagram, self.lengths = diagram, lengths
        _, layout = renderer.render(diagram.emit(lengths=lengths, labels=False))
        self.graph = LayeredGraph(layout, ignore=ignore)
        self.pre_graph = PreGraph(layout["pre"], diagram)
        self.optimum, self.goal = self.graph.solve()

    def text(self, node_order, edge_order, labels):
        return self.diagram.emit(node_order=node_order, edge_order=edge_order, lengths=self.lengths, labels=labels)

    def layering(self, oracle, node_order, edge_order):
        declared = Diagram(self.text(node_order, edge_order, labels=False))
        return oracle.layering(self.pre_graph, node_order=list(declared.nodes), edge_order=[e.dagre_id for e in declared.edges])

    def score(self, oracle, target, node_order, edge_order):
        layering = self.layering(oracle, node_order, edge_order)
        return (*self.graph.crossings(layering), inversions(layering, target))

    def start(self, target):
        position = {v: i for layer in target for i, v in enumerate(layer)}
        first_dummy = {}
        for v, n in self.graph.nodes.items():
            if n["dummy"] in ("edge", "edge-label") and n["edge"]:
                name = n["edge"][2]
                if name not in first_dummy or self.graph.rank[v] < self.graph.rank[first_dummy[name]]:
                    first_dummy[name] = v
        nodes = sorted(self.diagram.nodes, key=lambda v: (self.graph.rank[v], position[v]))
        edges = sorted(
            self.diagram.edges,
            key=lambda e: (self.graph.rank[e.src], position[e.src], position[first_dummy[e.dagre_id]] if e.dagre_id in first_dummy else 0, e.index),
        )
        return nodes, [e.index for e in edges]

    def run(self, oracle, budget):
        best = None
        for target in (self.optimum, [layer[::-1] for layer in self.optimum]):
            result = self.climb(oracle, target=target, budget=budget)
            if best is None or result[2][:2] < best[2][:2]:
                best = result
            if best[2][:2] <= self.goal:
                break
        return best

    def climb(self, oracle, target, budget):
        nodes, edges = self.start(target)
        best = self.score(oracle, target, nodes, edges)
        n, m = len(nodes), len(edges)
        space = [("nodes", i, j) for i in range(n) for j in range(n) if j != i] + [("edges", i, j) for i in range(m) for j in range(m) if j != i]
        cursor, since_improvement, evaluations = 0, 0, 1
        while best[:2] > self.goal and since_improvement < len(space) and evaluations < budget:
            kind, i, j = space[cursor]
            candidate = (moved(nodes, i, j), edges) if kind == "nodes" else (nodes, moved(edges, i, j))
            value = self.score(oracle, target, *candidate)
            evaluations += 1
            if value < best:
                (nodes, edges), best, since_improvement = candidate, value, 0
            else:
                since_improvement += 1
            cursor = (cursor + 1) % len(space)
        return nodes, edges, best
