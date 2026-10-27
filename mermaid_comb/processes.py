import contextlib
import json
import os
import re
import selectors
import signal
import subprocess
import tempfile
from pathlib import Path

ERROR_LINE = re.compile(r"^\w*Error: ")
RENDER_OPTIONS = {"theme": "neutral", "background": "white", "width": 800, "scale": 2}
EXIT_GRACE_SECONDS = 30


class LineProcess:
    def __init__(self, args, timeout, env=None):
        self.name, self.timeout, self.broken = Path(args[1]).name, timeout, False
        self.stderr = tempfile.TemporaryFile(mode="w+")
        self.process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr, text=True, env=env, start_new_session=True)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, events=selectors.EVENT_READ)
        self.next_id = 0
        try:
            if json.loads(self.read_line()).get("ready") is not True:
                raise self.failure("did not start")
        except (RuntimeError, ValueError):
            self.close()
            raise

    def failure(self, reason):
        self.broken = True
        self.stderr.seek(0)
        lines = [line.strip() for line in self.stderr.read().splitlines() if line.strip()]
        errors = [line for line in lines if ERROR_LINE.match(line)]
        detail = errors[0] if errors else " | ".join(lines[-3:])
        return RuntimeError(f"{self.name} {reason}" + (f": {detail}" if detail else ""))

    def read_line(self):
        if not self.selector.select(timeout=self.timeout):
            raise self.failure(f"gave no answer within {self.timeout} s")
        line = self.process.stdout.readline()
        if not line:
            raise self.failure(f"exited with code {self.process.wait()}")
        return line

    def call(self, payload):
        self.next_id += 1
        try:
            self.process.stdin.write(json.dumps({"id": self.next_id, **payload}) + "\n")
            self.process.stdin.flush()
        except BrokenPipeError:
            raise self.failure(f"exited with code {self.process.wait()}") from None
        reply = json.loads(self.read_line())
        if reply.get("id") != self.next_id:
            raise self.failure(f"answered request {reply.get('id')} instead of {self.next_id}")
        if "error" in reply:
            raise RuntimeError(f"{self.name}: {reply['error']}")
        return reply

    def close(self):
        with contextlib.suppress(BrokenPipeError):
            self.process.stdin.close()
        try:
            self.process.wait(timeout=0 if self.broken else EXIT_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            pass
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(self.process.pid, signal.SIGKILL)
        self.process.wait()
        self.selector.close()
        self.process.stdout.close()
        self.stderr.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class Renderer(LineProcess):
    def __init__(self, runtime, mermaid_dir=None):
        options = json.dumps({**RENDER_OPTIONS, "mermaidDir": str(mermaid_dir or runtime.traced)})
        super().__init__(["node", runtime.script("render_server.mjs"), options], timeout=120, env=runtime.env())

    def render(self, text):
        reply = self.call({"text": text})
        if len(reply["trace"]) > 1:
            raise ValueError(f"expected one dagre layout per render, got {len(reply['trace'])}; a subgraph with no edge to the outside is laid out separately and is not supported")
        return reply["svg"], reply["trace"][0] if reply["trace"] else None


class OrderOracle(LineProcess):
    def __init__(self, runtime):
        super().__init__(["node", runtime.script("order_oracle.mjs")], timeout=60, env=runtime.env())
        self.loaded = None

    def layering(self, pre_graph, node_order, edge_order):
        if self.loaded is not pre_graph:
            self.call({"load": {"pre": pre_graph.pre, "real": sorted(pre_graph.real), "owner": pre_graph.owner}})
            self.loaded = pre_graph
        return self.call({"permute": {"nodes": node_order, "edges": edge_order}})["layering"]
