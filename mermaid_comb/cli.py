import contextlib
import io
import random
import sys
import time
from pathlib import Path

import click

from . import runtime as runtime_module
from .diagram import Diagram
from .layered_model import LayeredGraph
from .pipeline import comb
from .processes import OrderOracle, Renderer
from .realiser import PreGraph
from .svg_check import defects, problems, read_svg

SAMPLES = Path(__file__).parent / "samples"
FAILURES = (ValueError, RuntimeError, OSError)


def fail(error):
    click.echo(f"mermaid-comb: {error}", err=True)
    sys.exit(2)


def clock():
    started = time.perf_counter()

    def log(message):
        click.echo(f"[{time.perf_counter() - started:5.1f}s] {message}", err=True)

    return log


@click.group()
@click.version_option(package_name="mermaids-comb")
def main():
    pass


@main.command()
@click.argument("source", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("-o", "--out", required=True, type=click.Path(dir_okay=False, writable=True, path_type=Path), help="Where to write the combed diagram.")
@click.option("--budget", default=1000, show_default=True, type=click.IntRange(min=1), help="Declaration-order evaluations per climb.")
@click.option("--max-renders", default=400, show_default=True, type=click.IntRange(min=1), help="Real renders allowed for the label stage.")
@click.option("--workers", default=4, show_default=True, type=click.IntRange(min=1), help="Order oracles run in parallel (Node processes, no browser).")
@click.option("--max-slack", default=3, show_default=True, type=click.IntRange(min=1), help="Spare ranks the ideal layout may use when one leaves crossings.")
def solve(source, out, budget, max_renders, workers, max_slack):
    """Comb SOURCE: the fewest crossings Mermaid's dagre can draw, written to --out."""
    if not out.resolve().parent.is_dir():
        fail(f"the directory of --out does not exist: {out.resolve().parent}")
    log = clock()
    try:
        combed, remaining, stage1 = comb(source.read_text(), runtime=runtime_module.installed(), budget=budget, max_renders=max_renders, workers=workers, max_slack=max_slack, log=log)
        out.write_text(combed)
    except FAILURES as error:
        fail(error)
    bound = f"ideal layout: {stage1['edge_crossings']} edge crossings, optimal within {stage1['slack']} spare rank(s)" if stage1["proven"] else "ideal layout not proven optimal"
    log(f"done: {len(remaining)} rendered defects ({bound}), written to {out}")
    for line in remaining:
        click.echo(f"  {line}", err=True)
    sys.exit(1 if remaining else 0)


@main.command()
@click.argument("files", nargs=-1, required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
def check(files):
    """Count crossings, edges under nodes and label collisions in .mmd or .svg FILES."""
    total = 0
    try:
        with renderer_for(files) as renderer:
            for path in files:
                svg = path.read_text() if path.suffix == ".svg" else renderer.render(path.read_text())[0]
                found = defects(io.StringIO(svg))
                listed = problems(found)
                total += len(listed)
                click.echo(f"{path.name}: nodes={found['nodes']} edges={found['edges']} crossings={len(found['crossings'])} under_nodes={len(found['under_nodes'])} label_collisions={len(found['label_collisions'])}")
                for line in listed:
                    click.echo(f"  {line}")
    except FAILURES as error:
        fail(error)
    sys.exit(1 if total else 0)


def renderer_for(files):
    if all(path.suffix == ".svg" for path in files):
        return contextlib.nullcontext()
    installed = runtime_module.installed()
    return Renderer(installed, mermaid_dir=installed.pristine)


@main.command()
def setup():
    """Install the pinned Mermaid, Puppeteer and headless Chrome into the user cache."""
    try:
        runtime_module.setup(log=clock())
    except FAILURES as error:
        fail(error)


def canonical(graph, layering):
    def name(v):
        n = graph.nodes[v]
        if n["dummy"] is None:
            return v
        if n["dummy"] == "border":
            return f"border:{n['parent']}:{n.get('borderType') or v[:3]}:{graph.rank[v]}"
        return f"dummy:{n['edge'][2]}:{graph.rank[v]}"

    return [[name(v) for v in layer] for layer in layering]


def geometry(svg):
    nodes, edges, labels = read_svg(io.StringIO(svg))
    return nodes, sorted(edges), sorted(labels)


@main.command()
@click.option("--orders", default=8, show_default=True, type=click.IntRange(min=1), help="Random declaration orders replayed per sample.")
def parity(orders):
    """Check the traced Mermaid copy against the pristine one, and the order replay against real renders."""
    mismatches = 0
    try:
        installed = runtime_module.installed()
        with Renderer(installed, mermaid_dir=installed.pristine) as pristine, Renderer(installed) as traced, OrderOracle(installed) as oracle:
            for sample in sorted(SAMPLES.glob("*.mmd")):
                text = sample.read_text()
                same_geometry = geometry(pristine.render(text)[0]) == geometry(traced.render(text)[0])
                diagram = Diagram(text)
                _, base = traced.render(text)
                pre_graph, base_graph = PreGraph(base["pre"], diagram), LayeredGraph(base)
                rng = random.Random(sample.name)
                agree = rank_changes = 0
                for _ in range(orders):
                    nodes = rng.sample(list(diagram.nodes), k=len(diagram.nodes))
                    edges = rng.sample([e.index for e in diagram.edges], k=len(diagram.edges))
                    declared = Diagram(diagram.emit(node_order=nodes, edge_order=edges))
                    _, layout = traced.render(declared.text)
                    actual = LayeredGraph(layout)
                    if any(actual.rank[v] != base_graph.rank[v] for v in diagram.nodes):
                        rank_changes += 1
                        continue
                    predicted = oracle.layering(pre_graph, node_order=list(declared.nodes), edge_order=[e.dagre_id for e in declared.edges])
                    agree += canonical(base_graph, predicted) == canonical(actual, actual.layers)
                compared = orders - rank_changes
                mismatches += (not same_geometry) + (compared - agree)
                if compared == 0:
                    mismatches += 1
                    click.echo(f"{sample.name}: every random order moved the ranks, so the order replay was not compared")
                click.echo(f"{sample.name}: traced geometry identical to pristine: {same_geometry}; order replay matches the render: {agree}/{compared} (ranks moved in {rank_changes} of {orders} orders)")
    except FAILURES as error:
        fail(error)
    sys.exit(1 if mismatches else 0)
