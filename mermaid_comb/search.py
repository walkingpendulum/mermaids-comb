import io
import random

from . import syntax
from .svg_check import defects, problems


def shuffled(group, rng, order):
    items, edges = group["items"][:], group["edges"][:]
    rng.shuffle(items)
    rng.shuffle(edges)
    out = group["head"] + group["fixed"]
    for item in items + edges:
        if "items" in item:
            out += shuffled(item, rng=rng, order=order)
        else:
            if item["edge"] is not None:
                order.append(item["edge"])
            out += item["lines"]
    return out + group["tail"]


def variant(parsed, rng):
    header, root, styles, edge_count = parsed
    order = []
    body = shuffled(root, rng=rng, order=order)
    new_index = {old: new for new, old in enumerate(order)}
    return "\n".join([*header, *body, *(syntax.restyle(line, new_index=new_index, edge_count=edge_count) for line in styles)]) + "\n"


def search(text, renderer, trials, seed, stop_at_zero, log):
    parsed = syntax.parse(text)
    rng = random.Random(seed)
    candidates = [text] + [variant(parsed, rng=rng) for _ in range(trials)]
    best, tally = None, {}
    for index, candidate in enumerate(candidates):
        svg, _ = renderer.render(candidate)
        count = len(problems(defects(io.StringIO(svg))))
        if index:
            tally[count] = tally.get(count, 0) + 1
        else:
            log(f"original order: {count} defects")
        if best is None or count < best[0]:
            best = (count, candidate)
        if stop_at_zero and count == 0:
            break
    log("trials by defects: " + ", ".join(f"{k}: {v}" for k, v in sorted(tally.items())))
    return best
