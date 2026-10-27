import copy

import pytest

from mermaid_comb import pipeline
from mermaid_comb.diagram import Diagram
from mermaid_comb.ideal_check import check, recount
from mermaid_comb.ideal_layout import Problem, optimal_layering
from mermaid_comb.meaning import differences

HEADER = "---\nconfig:\n  layout: dagre\n---\nflowchart LR\n"
GROUPED = HEADER + """  Api["api"]
  subgraph Store["storage"]
    Db[("db")]
    Bucket[("bucket")]
  end
  App["app"]
  App -->|calls| Api
  Api ==>|writes| Db
  App --->|downloads from| Bucket
  style Store stroke:#888
"""


def diagram(body):
    return Diagram(HEADER + body)


def test_emit_round_trips_the_source():
    assert Diagram(GROUPED).emit() == GROUPED


def test_emit_reorders_and_stretches_without_touching_lines():
    source = Diagram(GROUPED)
    text = source.emit(node_order=["App", "Bucket", "Db", "Api"], edge_order=[2, 0, 1], lengths={0: 3})
    assert text.index('App["app"]') < text.index('Api["api"]')
    assert "App ---->|calls| Api" in text
    assert differences(source, Diagram(text)) == []


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ('  A["a"]\n  B["b"]\n  C["c"]\n  A --> B --> C\n', "chained edges"),
        ('  subgraph G["g"]\n    subgraph H["h"]\n      A["a"]\n    end\n  end\n  B["b"]\n  A --> B\n', "nested subgraph"),
        ('  A["a"]\n  B["b"]\n  A -->|x| B\n  A -->|y| B\n', "parallel edges"),
        ('  A["a"]\n  B["b"]\n  A -- text --> B\n', "unsupported edge form"),
        ('  subgraph G["g"]\n    A["a"]\n  end\n  B["b"]\n  B --> G\n', "edges to a subgraph"),
        ('  A["a"]\n  A --> B\n', "never declared"),
    ],
)
def test_diagram_refuses_unsupported_input(body, message):
    with pytest.raises(ValueError, match=message):
        diagram(body)


def test_diagram_requires_dagre():
    with pytest.raises(ValueError, match="layout: dagre"):
        Diagram("flowchart LR\n  A --> B\n")


def test_cycle_is_refused():
    with pytest.raises(ValueError, match="cycle"):
        Problem.from_diagram(diagram('  A["a"]\n  B["b"]\n  A --> B\n  B --> A\n')).depths()


def test_k22_uncrosses_with_one_spare_rank():
    problem = Problem.from_diagram(diagram('  A["a"]\n  B["b"]\n  C["c"]\n  D["d"]\n  A --> C\n  A --> D\n  B --> C\n  B --> D\n'))
    result = optimal_layering(problem, slack_ranks=1)
    assert (result["proven"], result["edge_crossings"]) == (True, 0)
    assert check(problem, result) == []


def test_k33_keeps_a_crossing():
    edges = "".join(f"  {u} --> {v}\n" for u in "ABC" for v in "XYZ")
    problem = Problem.from_diagram(diagram("".join(f'  {v}["{v}"]\n' for v in "ABCXYZ") + edges))
    result = optimal_layering(problem, slack_ranks=2)
    assert result["edge_crossings"] >= 1
    assert check(problem, result) == []


def test_edges_into_a_group_stay_inside_its_box():
    problem = Problem.from_diagram(Diagram(GROUPED))
    result = optimal_layering(problem, slack_ranks=1)
    assert result["proven"]
    assert check(problem, result) == []


def test_check_catches_a_corrupted_layering():
    problem = Problem.from_diagram(diagram('  A["a"]\n  B["b"]\n  C["c"]\n  D["d"]\n  A --> C\n  A --> D\n  B --> C\n  B --> D\n'))
    result = optimal_layering(problem, slack_ranks=1)
    broken = copy.deepcopy(result)
    row = next(row for row in broken["layering"] if len(row) >= 2)
    row[0], row[1] = row[1], row[0]
    assert check(problem, broken) != []


@pytest.mark.parametrize(
    ("old", "new"),
    [("|writes|", "|stores|"), ("Api ==>", "Api -->"), ('Db[("db")]', 'Db[("database")]')],
)
def test_meaning_check_rejects_semantic_edits(old, new):
    assert differences(Diagram(GROUPED), Diagram(GROUPED.replace(old, new))) != []


def test_meaning_check_keeps_the_inputs_own_invisible_edges():
    source = Diagram(GROUPED.replace("  style", "  App ~~~ Db\n  style"))
    assert differences(source, source) == []
    assert differences(source, Diagram(GROUPED)) == ["invisible edges of the input"]


def test_meaning_check_requires_a_comment_on_invisible_edges():
    assert differences(Diagram(GROUPED), Diagram(GROUPED.replace("  style", "  App ~~~ Db\n  style"))) != []
    assert differences(Diagram(GROUPED), Diagram(GROUPED.replace("  style", "  %% layout\n  App ~~~ Db\n  style"))) == []


K22 = '  A["a"]\n  B["b"]\n  C["c"]\n  D["d"]\n  A --> C\n  A --> D\n  B --> C\n  B --> D\n'


def fake_stage1(monkeypatch, outcomes):
    calls = []

    def fake(problem, slack_ranks):
        calls.append(slack_ranks)
        outcome = outcomes[slack_ranks]
        if isinstance(outcome, Exception):
            raise outcome
        return {"proven": True, "slack": slack_ranks, "edge_crossings": outcome[0], "border_crossings": outcome[1], "ranks": {}, "layering": []}

    monkeypatch.setattr(pipeline, name="optimal_layering", value=fake)
    monkeypatch.setattr(pipeline, name="check", value=lambda problem, result: [])
    monkeypatch.setattr(pipeline, name="recount", value=lambda problem, result: (result["edge_crossings"], result["border_crossings"]))
    return calls


@pytest.mark.parametrize(
    ("outcomes", "calls", "chosen"),
    [
        ({1: (0, 1), 3: (0, 0)}, [1], 1),
        ({1: (1, 0), 3: (0, 0)}, [1, 3], 3),
        ({1: (1, 0), 3: (1, 1)}, [1, 3], 1),
        ({1: (1, 0), 3: RuntimeError("no layout found: UNKNOWN")}, [1, 3], 1),
    ],
)
def test_stage1_escalates_only_on_edge_crossings_and_keeps_the_best(monkeypatch, outcomes, calls, chosen):
    seen = fake_stage1(monkeypatch, outcomes)
    result = pipeline.ideal(diagram(K22), max_slack=3, log=lambda message: None)
    assert seen == calls
    assert result["slack"] == chosen


def test_stage1_failure_without_a_fallback_is_raised(monkeypatch):
    fake_stage1(monkeypatch, {1: RuntimeError("no layout found: UNKNOWN")})
    with pytest.raises(RuntimeError, match="UNKNOWN"):
        pipeline.ideal(diagram(K22), max_slack=1, log=lambda message: None)


def test_stopping_floor_trusts_only_proven_counts():
    assert pipeline.stopping_floor({"proven": True, "edge_crossings": 2}) == 2
    assert pipeline.stopping_floor({"proven": False, "edge_crossings": 2}) == 0


def test_check_allows_overcounting_only_when_not_proven():
    problem = Problem.from_diagram(diagram(K22))
    result = optimal_layering(problem, slack_ranks=1)
    assert recount(problem, result) == (result["edge_crossings"], result["border_crossings"])
    overcounted = {**result, "edge_crossings": result["edge_crossings"] + 1}
    assert check(problem, overcounted) != []
    assert check(problem, {**overcounted, "proven": False}) == []
    undercounted = {**result, "proven": False, "edge_crossings": -1}
    assert check(problem, undercounted) != []


@pytest.mark.parametrize(("old", "new"), [('subgraph Store["storage"]', 'subgraph Store["archive"]'), ("flowchart LR\n", "flowchart LR\n  direction TB\n")])
def test_meaning_check_covers_subgraph_and_direction_lines(old, new):
    edited = GROUPED.replace(old, new) if old in GROUPED else GROUPED.replace("flowchart LR\n", new)
    assert differences(Diagram(GROUPED), Diagram(edited)) != []
