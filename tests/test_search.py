import random
from collections import Counter
from pathlib import Path

from mermaid_comb import syntax
from mermaid_comb.search import variant

SOURCE = (Path(__file__).parent.parent / "mermaid_comb" / "samples" / "learning.mmd").read_text()


def test_a_variant_keeps_every_line():
    shuffled = variant(syntax.parse(SOURCE), rng=random.Random(3))
    assert Counter(shuffled.splitlines()) == Counter(SOURCE.rstrip("\n").splitlines())
    assert shuffled != SOURCE


def test_the_same_seed_gives_the_same_variants():
    parsed = syntax.parse(SOURCE)
    first, second = random.Random(7), random.Random(7)
    assert [variant(parsed, rng=first) for _ in range(5)] == [variant(parsed, rng=second) for _ in range(5)]


def test_link_styles_follow_their_edges():
    source = "---\nconfig:\n  layout: dagre\n---\nflowchart LR\n  A --> B\n  C --> D\n  linkStyle 1 stroke:red\n"
    for seed in range(6):
        shuffled = variant(syntax.parse(source), rng=random.Random(seed)).splitlines()
        edges = [line for line in shuffled if "-->" in line]
        assert shuffled[-1] == f"  linkStyle {edges.index('  C --> D')} stroke:red"
