import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

JS = Path(__file__).parent / "js"
SHIPPED = ("*.json", "*.mjs", "*.html")
MINIMUM_NODE = (22, 12, 0)
ERROR_LINE = re.compile(r"^\w*Error: ")


def shipped_files():
    return sorted({path for pattern in SHIPPED for path in JS.glob(pattern)})


def cache_root():
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "mermaid-comb"


def fingerprint():
    digest = hashlib.sha256()
    for path in shipped_files():
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


class Runtime:
    def __init__(self, root):
        self.root = root
        self.traced = root / "traced"
        self.pristine = root / "node_modules" / "mermaid" / "dist"

    def env(self):
        return dict(os.environ, PUPPETEER_CACHE_DIR=str(self.root / "browsers"))

    def script(self, name):
        return str(self.root / name)


def location():
    return cache_root() / f"runtime-{fingerprint()}"


def installed():
    root = location()
    if not (root / "ready").exists():
        raise RuntimeError("the Node runtime is not installed; run `mermaid-comb setup`")
    return Runtime(root)


def run(args, cwd, env):
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        lines = [line.strip() for line in (result.stderr or result.stdout).splitlines() if line.strip()]
        errors = [line for line in lines if ERROR_LINE.match(line)]
        detail = errors[0] if errors else " | ".join(lines[-4:])
        raise RuntimeError(f"`{' '.join(args)}` failed with exit code {result.returncode}: {detail}")
    return result.stdout


def require_node():
    for tool in ("node", "npm", "npx"):
        if shutil.which(tool) is None:
            raise RuntimeError(f"`{tool}` is not on PATH; install Node.js {'.'.join(map(str, MINIMUM_NODE))} or later")
    version = subprocess.run(["node", "--version"], capture_output=True, text=True, check=True).stdout.strip()
    if tuple(int(part) for part in version.lstrip("v").split(".")[:3]) < MINIMUM_NODE:
        raise RuntimeError(f"Node.js {version} is too old; the pinned Puppeteer needs {'.'.join(map(str, MINIMUM_NODE))} or later")


def build(partial, log):
    for path in shipped_files():
        shutil.copy2(path, dst=partial / path.name)
    env = dict(os.environ, PUPPETEER_SKIP_DOWNLOAD="1", PUPPETEER_CACHE_DIR=str(partial / "browsers"))
    log("installing the pinned Mermaid, dagre-d3-es and Puppeteer with npm ci")
    run(["npm", "ci", "--no-audit", "--no-fund"], cwd=partial, env=env)
    log("downloading Puppeteer's pinned headless Chrome")
    run(["npx", "--no-install", "puppeteer", "browsers", "install", "chrome-headless-shell"], cwd=partial, env=env)
    log("building the traced Mermaid copy")
    run(["node", "trace_patch.mjs", "build", str(partial / "traced")], cwd=partial, env=env)
    (partial / "ready").write_text(fingerprint() + "\n")


def setup(log):
    require_node()
    root = location()
    if (root / "ready").exists():
        log(f"the runtime is already installed in {root}")
        return Runtime(root)
    root.parent.mkdir(parents=True, exist_ok=True)
    partial = Path(tempfile.mkdtemp(prefix=f"{root.name}.partial-", dir=root.parent))
    try:
        build(partial, log=log)
        try:
            partial.rename(root)
        except OSError:
            if (root / "ready").exists():
                log(f"another setup finished first; keeping {root}")
                return Runtime(root)
            shutil.rmtree(root)
            partial.rename(root)
        log(f"installed in {root}")
    finally:
        shutil.rmtree(partial, ignore_errors=True)
    return Runtime(root)
