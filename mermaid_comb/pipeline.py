import concurrent.futures
import contextlib
import io

from .diagram import Diagram
from .ideal_check import check, recount
from .ideal_layout import Problem, optimal_layering
from .meaning import differences
from .processes import OrderOracle, Renderer
from .realiser import Realiser, moves
from .svg_check import defects, problems

INVISIBLE_COMMENT = "  %% layout: invisible rank edge, steers dagre's crossing reduction"
CACHE_AUDITS = 5


def rendered_defects(renderer, text):
    svg, _ = renderer.render(text)
    return sorted(problems(defects(io.StringIO(svg))))


def crossings_of(result):
    return result["edge_crossings"], result["border_crossings"]


def ideal(diagram, max_slack, log):
    problem = Problem.from_diagram(diagram)
    best = None
    for slack in sorted({1, max_slack}):
        try:
            result = optimal_layering(problem, slack_ranks=slack)
        except RuntimeError as error:
            if best is None:
                raise
            log(f"stage 1: no layout within {slack} spare ranks ({error}); keeping the one-spare-rank layout")
            break
        violations = check(problem, result)
        if violations:
            raise RuntimeError(f"stage 1 layout failed its recount: {violations}")
        result["edge_crossings"], result["border_crossings"] = recount(problem, result)
        verdict = "optimal" if result["proven"] else "best found, not proven optimal"
        log(f"stage 1: {result['edge_crossings']} edge crossings, {result['border_crossings']} group-border crossings, {verdict} within {slack} spare rank(s)")
        if best is None or crossings_of(result) < crossings_of(best):
            best = result
        if best["edge_crossings"] == 0:
            break
    return best


def stopping_floor(stage1):
    return stage1["edge_crossings"] if stage1["proven"] else 0


def invisible_candidate(diagram, lengths, half, pair, renderer, base):
    u, w = pair
    line = f"  {u} {'~' * (2 + (half[w] - half[u]) // 2)} {w}"
    extended = Diagram(diagram.emit(lengths=lengths, extra_lines=[INVISIBLE_COMMENT, line]))
    invisible = {e.dagre_id for e in extended.edges if e.invisible}
    candidate = Realiser(extended, lengths={e.index: e.length for e in extended.edges}, renderer=renderer, ignore=invisible)
    if any(candidate.graph.rank[v] != base.graph.rank[v] for v in diagram.nodes):
        return None
    return candidate, line.strip()


def realise(diagram, half, renderer, oracles, budget, log):
    lengths = {e.index: (half[e.dst] - half[e.src]) // 2 for e in diagram.edges if not e.invisible}
    realiser = Realiser(diagram, lengths=lengths, renderer=renderer, ignore={e.dagre_id for e in diagram.edges if e.invisible})
    nodes, edges, best = realiser.run(oracles[0], budget=budget)
    log(f"stage 2: declaration order reaches {best[:2]}; dagre's layered optimum is {realiser.goal}")
    if best[:2] <= realiser.goal:
        return realiser, nodes, edges, best
    existing = {(e.src, e.dst) for e in diagram.edges}
    pairs = sorted(
        ((u, w) for u in diagram.nodes for w in diagram.nodes if half[w] > half[u] and (u, w) not in existing),
        key=lambda pair: half[pair[1]] - half[pair[0]],
    )
    candidates = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(oracles)) as pool:
        for round_budget in (budget // 4, budget):
            for start in range(0, len(pairs), len(oracles)):
                chunk = pairs[start : start + len(oracles)]
                for pair in chunk:
                    if pair not in candidates:
                        candidates[pair] = invisible_candidate(diagram, lengths, half, pair, renderer=renderer, base=realiser)
                live = [candidates[pair] for pair in chunk if candidates[pair] is not None]
                outcomes = list(pool.map(lambda job: job[1][0].run(oracles[job[0]], budget=round_budget), enumerate(live)))
                for (candidate, line), (c_nodes, c_edges, c_best) in zip(live, outcomes):
                    if c_best[:2] < best[:2]:
                        realiser, nodes, edges, best = candidate, c_nodes, c_edges, c_best
                        log(f"stage 2: invisible edge `{line}` reaches {best[:2]}")
                        if best[:2] <= realiser.goal:
                            return realiser, nodes, edges, best
    return realiser, nodes, edges, best


def polish(realiser, nodes, edges, renderer, oracle, layered_goal, floor, max_renders, log):
    lengths = dict(realiser.lengths)
    stats = {"renders": 0, "cache_hits": 0, "audits": 0}
    by_layering = {}

    def render_cost(n, e, l):
        stats["renders"] += 1
        found = rendered_defects(renderer, realiser.diagram.emit(node_order=n, edge_order=e, lengths=l))
        return (len(found), sum(l.values())), found

    def cost(n, e, l):
        if l != realiser.lengths:
            return render_cost(n, e, l)[0]
        layering = realiser.layering(oracle, n, e)
        if realiser.graph.crossings(layering) > layered_goal:
            return None
        key = tuple(tuple(layer) for layer in layering)
        if key in by_layering:
            stats["cache_hits"] += 1
            if stats["audits"] < CACHE_AUDITS:
                stats["audits"] += 1
                if render_cost(n, e, l)[1] != by_layering[key][1]:
                    raise RuntimeError("the same dagre layering rendered different defects; the render cache is unsound")
            return by_layering[key][0]
        by_layering[key] = render_cost(n, e, l)
        return by_layering[key][0]

    best = cost(nodes, edges, lengths)
    log(f"stage 3: {best[0]} rendered defects with labels")
    improved = True
    while improved and best[0] > floor and stats["renders"] < max_renders:
        improved = False
        candidates = [("nodes", (moved_nodes, edges, lengths)) for moved_nodes in moves(nodes)]
        candidates += [("edges", (nodes, moved_edges, lengths)) for moved_edges in moves(edges)]
        candidates += [("length", (nodes, edges, {**lengths, e.index: lengths[e.index] + 1})) for e in realiser.diagram.edges if not e.invisible]
        for kind, (n, e, l) in candidates:
            value = cost(n, e, l)
            if value is not None and value < best:
                nodes, edges, lengths, best, improved = n, e, l, value, True
                log(f"stage 3: {kind} move leaves {best[0]} rendered defects")
                break
            if stats["renders"] >= max_renders:
                break
    log(f"stage 3: {stats['renders']} renders, {stats['cache_hits']} cache hits, {stats['audits']} cache hits re-rendered and matched")
    return nodes, edges, lengths


def comb(text, runtime, budget, max_renders, workers, max_slack, log):
    diagram = Diagram(text)
    if not any(not e.invisible for e in diagram.edges):
        raise ValueError("the flowchart has no edges to comb")
    stage1 = ideal(diagram, max_slack=max_slack, log=log)
    with Renderer(runtime) as renderer, contextlib.ExitStack() as stack:
        oracles = [stack.enter_context(OrderOracle(runtime)) for _ in range(workers)]
        realiser, nodes, edges, best = realise(diagram, stage1["ranks"], renderer=renderer, oracles=oracles, budget=budget, log=log)
        nodes, edges, lengths = polish(realiser, nodes, edges, renderer=renderer, oracle=oracles[0], layered_goal=best[:2], floor=stopping_floor(stage1), max_renders=max_renders, log=log)
        combed = realiser.diagram.emit(node_order=nodes, edge_order=edges, lengths=lengths)
        remaining = rendered_defects(renderer, combed)
    changed = differences(diagram, Diagram(combed))
    if changed:
        raise RuntimeError(f"the combed diagram changed the meaning: {changed}")
    return combed, remaining, stage1
