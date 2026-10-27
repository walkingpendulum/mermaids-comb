import itertools


def expected_inside(problem, rank, o, g, t):
    members = problem.groups[g]
    if not o.startswith("edge"):
        return o in members
    u, v = problem.edges[int(o[4:])]
    if u in members:
        return True
    if v not in members:
        return False
    source_groups = [h for h, hm in problem.groups.items() if u in hm]
    return all(t > max(rank[m] for m in problem.groups[h]) + 1 for h in source_groups)


def structure(problem, result):
    rank, layering = result["ranks"], result["layering"]
    violations = [f"edge {u}->{v} does not advance one node rank" for u, v in problem.edges if rank[v] < rank[u] + 2]
    for t, row in enumerate(layering):
        expected = {v for v in problem.nodes if rank[v] == t}
        expected |= {f"edge{i}" for i, (u, v) in enumerate(problem.edges) if rank[u] < t < rank[v]}
        for g, members in problem.groups.items():
            if min(rank[m] for m in members) - 1 <= t <= max(rank[m] for m in members) + 1:
                expected |= {f"left:{g}", f"right:{g}"}
        if set(row) != expected or len(row) != len(set(row)):
            violations.append(f"rank {t} holds {sorted(row)} instead of {sorted(expected)}")
            continue
        for g in problem.groups:
            if f"left:{g}" not in row:
                continue
            lo, hi = row.index(f"left:{g}"), row.index(f"right:{g}")
            for i, o in enumerate(row):
                if o not in (f"left:{g}", f"right:{g}") and expected_inside(problem, rank, o, g, t) != (lo < i < hi):
                    violations.append(f"rank {t}: {o} is on the wrong side of group {g}")
    return violations


def recount(problem, result):
    rank, layering = result["ranks"], result["layering"]
    position = {(o, t): i for t, row in enumerate(layering) for i, o in enumerate(row)}
    chains = {}
    for i, (u, v) in enumerate(problem.edges):
        chains[("edge", i)] = {t: position[(u if t == rank[u] else v if t == rank[v] else f"edge{i}", t)] for t in range(rank[u], rank[v] + 1)}
    for g in problem.groups:
        for side in ("left", "right"):
            chains[("border", f"{side}:{g}")] = {t: position[(f"{side}:{g}", t)] for t, row in enumerate(layering) if f"{side}:{g}" in row}
    edge_edge = edge_border = 0
    for (a, pa), (b, pb) in itertools.combinations(chains.items(), r=2):
        if a[0] == b[0] == "border":
            continue
        for t in set(pa) & set(pb):
            if t + 1 in pa and t + 1 in pb and (pa[t] - pb[t]) * (pa[t + 1] - pb[t + 1]) < 0:
                if a[0] == b[0] == "edge":
                    edge_edge += 1
                else:
                    edge_border += 1
    return edge_edge, edge_border


def check(problem, result):
    violations = structure(problem, result)
    if violations:
        return violations
    counted = recount(problem, result)
    reported = (result["edge_crossings"], result["border_crossings"])
    exceeded = any(c > r for c, r in zip(counted, reported))
    if counted != reported if result["proven"] else exceeded:
        return [f"recount gives {counted[0]} edge and {counted[1]} border crossings, the solver reported {reported[0]} and {reported[1]}"]
    return []
