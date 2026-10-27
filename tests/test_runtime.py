import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from mermaid_comb import runtime
from mermaid_comb.processes import LineProcess

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js")


@pytest.mark.skipif(not (Path(__file__).parent.parent / ".git").exists(), reason="needs a git checkout")
def test_every_runtime_file_is_shipped_and_hashed():
    tracked = subprocess.run(["git", "ls-files", "mermaid_comb/js"], capture_output=True, text=True, cwd=Path(__file__).parent.parent, check=True).stdout.split()
    assert sorted(Path(name).name for name in tracked) == sorted(path.name for path in runtime.shipped_files())


def test_the_runtime_key_follows_every_shipped_file(tmp_path, monkeypatch):
    copy = tmp_path / "js"
    shutil.copytree(runtime.JS, dst=copy, ignore=shutil.ignore_patterns("node_modules"))
    monkeypatch.setattr(runtime, name="JS", value=copy)
    before = runtime.fingerprint()
    for path in runtime.shipped_files():
        original = path.read_bytes()
        path.write_bytes(original + b"\n")
        assert runtime.fingerprint() != before, path.name
        path.write_bytes(original)
    assert runtime.fingerprint() == before


def helper(tmp_path, body):
    script = tmp_path / "helper.mjs"
    script.write_text('import readline from "node:readline";\nimport { spawn } from "node:child_process";\n' + body)
    return ["node", str(script)]


@needs_node
def test_a_helper_that_dies_reports_its_error_line(tmp_path):
    args = helper(tmp_path, 'process.stdout.write(JSON.stringify({ ready: true }) + "\\n");\nfor await (const line of readline.createInterface({ input: process.stdin })) { process.stderr.write("RangeError: late failure\\n"); process.exit(1); }\n')
    process = LineProcess(args, timeout=10)
    with pytest.raises(RuntimeError, match="RangeError: late failure"):
        try:
            process.call({"x": 1})
            process.call({"x": 2})
        finally:
            process.close()


@needs_node
def test_a_hung_helper_and_its_children_are_killed_at_the_timeout(tmp_path):
    marker = f"sleep {4000 + time.time_ns() % 1000}"
    args = helper(tmp_path, f'spawn("sleep", ["{marker.split()[1]}"], {{ stdio: "ignore" }});\nprocess.stdout.write(JSON.stringify({{ ready: true }}) + "\\n");\nsetInterval(() => {{}}, 1000);\n')
    started = time.perf_counter()
    process = LineProcess(args, timeout=1)
    with pytest.raises(RuntimeError, match="gave no answer within 1 s"):
        try:
            process.call({"x": 1})
        finally:
            process.close()
    assert time.perf_counter() - started < 10
    time.sleep(0.5)
    assert subprocess.run(["pgrep", "-f", marker], capture_output=True, text=True).stdout.strip() == ""
