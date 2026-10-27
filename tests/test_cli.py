import http.server
import shutil
import threading
from pathlib import Path

import pytest
from click.testing import CliRunner

from mermaid_comb import runtime
from mermaid_comb.cli import main

SAMPLES = Path(__file__).parent.parent / "mermaid_comb" / "samples"
CLEAN_SVG = """<svg xmlns="http://www.w3.org/2000/svg"><g class="root">
<g class="node default" id="flowchart-A-0" transform="translate(50,50)"><g class="label" transform="translate(-10,-10)"><foreignObject width="20" height="20"/></g></g>
<g class="node default" id="flowchart-B-1" transform="translate(250,50)"><g class="label" transform="translate(-10,-10)"><foreignObject width="20" height="20"/></g></g>
<path class="flowchart-link" data-id="L_A_B_0" d="M80,50L220,50"/>
</g></svg>"""


def runtime_ready():
    try:
        runtime.installed()
        return True
    except RuntimeError:
        return False


needs_runtime = pytest.mark.skipif(not runtime_ready() or shutil.which("node") is None, reason="run `mermaid-comb setup` first")


@pytest.mark.parametrize(
    ("options", "message"),
    [
        (["--workers", "0"], "--workers"),
        (["--budget", "0"], "--budget"),
        (["--max-renders", "0"], "--max-renders"),
        (["--max-slack", "0"], "--max-slack"),
    ],
)
def test_solve_rejects_non_positive_options(tmp_path, options, message):
    result = CliRunner().invoke(main, args=["solve", str(SAMPLES / "crossing.mmd"), "-o", str(tmp_path / "out.mmd"), *options])
    assert result.exit_code == 2
    assert message in result.output


def test_solve_rejects_a_missing_output_directory(tmp_path):
    result = CliRunner().invoke(main, args=["solve", str(SAMPLES / "crossing.mmd"), "-o", str(tmp_path / "missing" / "out.mmd")])
    assert result.exit_code == 2
    assert "directory of --out" in result.output


def test_check_reads_an_svg_without_the_runtime(tmp_path):
    svg = tmp_path / "clean.svg"
    svg.write_text(CLEAN_SVG)
    result = CliRunner().invoke(main, args=["check", str(svg)])
    assert result.exit_code == 0
    assert "crossings=0 under_nodes=0 label_collisions=0" in result.output


def test_check_counts_a_crossing(tmp_path):
    nodes = "".join(
        f'<g class="node default" id="flowchart-{name}-{i}" transform="translate({x},{y})"><g class="label" transform="translate(-10,-10)"><foreignObject width="20" height="20"/></g></g>'
        for i, (name, x, y) in enumerate([("A", 50, 20), ("B", 350, 180), ("C", 50, 180), ("D", 350, 20)])
    )
    edges = '<path class="flowchart-link" data-id="L_A_B_0" d="M80,20L320,180"/><path class="flowchart-link" data-id="L_C_D_0" d="M80,180L320,20"/>'
    svg = tmp_path / "crossed.svg"
    svg.write_text(f'<svg xmlns="http://www.w3.org/2000/svg"><g class="root">{nodes}{edges}</g></svg>')
    result = CliRunner().invoke(main, args=["check", str(svg)])
    assert result.exit_code == 1
    assert "crossings=1" in result.output
    assert "A->B x C->D" in result.output


@needs_runtime
def test_solve_uncrosses_the_k22_sample(tmp_path):
    out = tmp_path / "out.mmd"
    result = CliRunner().invoke(main, args=["solve", str(SAMPLES / "crossing.mmd"), "-o", str(out)])
    assert result.exit_code == 0, result.output
    checked = CliRunner().invoke(main, args=["check", str(out)])
    assert "crossings=0 under_nodes=0 label_collisions=0" in checked.output


def test_check_refuses_a_malformed_svg(tmp_path):
    svg = tmp_path / "bad.svg"
    svg.write_text("not xml")
    result = CliRunner().invoke(main, args=["check", str(svg)])
    assert result.exit_code == 2
    assert "not a readable SVG" in result.output


@needs_runtime
def test_solve_keeps_invisible_edges_of_the_input(tmp_path):
    source = tmp_path / "in.mmd"
    source.write_text((SAMPLES / "crossing.mmd").read_text() + "  %% keep the apps apart\n  Web ~~~ Mobile\n")
    out = tmp_path / "out.mmd"
    result = CliRunner().invoke(main, args=["solve", str(source), "-o", str(out)])
    assert result.exit_code in (0, 1), result.output
    assert "  Web ~~~ Mobile" in out.read_text()


@needs_runtime
def test_rendering_fetches_nothing_outside_mermaid(tmp_path):
    hits = []

    class Recorder(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(404)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Recorder)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        source = tmp_path / "fetch.mmd"
        source.write_text(f'---\nconfig:\n  layout: dagre\n---\nflowchart LR\n  A["<img src=\'http://127.0.0.1:{server.server_port}/hit.png\'> a"]\n  B["b"]\n  A --> B\n')
        CliRunner().invoke(main, args=["check", str(source)])
    finally:
        server.shutdown()
    assert hits == []
