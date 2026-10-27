import argparse
import datetime
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REPOSITORY = "walkingpendulum/mermaids-comb"
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
HEADING = re.compile(r"^## \[(?P<name>[^\]]+)\]", flags=re.M)
EXIT = {"usage": 2, "preflight": 3, "checks": 4, "prepare": 5, "publish": 6, "verify": 7}


class Failure(Exception):
    def __init__(self, phase, message):
        super().__init__(message)
        self.phase = phase


def run(phase, args, capture=True):
    result = subprocess.run(args, cwd=ROOT, capture_output=capture, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()[-3:] if capture else []
        raise Failure(phase, f"`{' '.join(args)}` failed with exit code {result.returncode}" + (": " + " | ".join(detail) if detail else ""))
    return result.stdout.strip() if capture else ""


def parse_version(text):
    return tuple(int(part) for part in text.split("."))


def changelog_sections(text):
    headings = list(HEADING.finditer(text))
    return {m.group("name"): text[m.end() : headings[i + 1].start() if i + 1 < len(headings) else len(text)] for i, m in enumerate(headings)}


def release_notes(text, version):
    body = changelog_sections(text).get(version, "")
    return body.split("\n", maxsplit=1)[1].strip() if "\n" in body else ""


def preflight(version):
    if not VERSION.match(version):
        raise Failure("usage", f"{version} is not a MAJOR.MINOR.PATCH version")
    if run("preflight", ["git", "branch", "--show-current"]) != "main":
        raise Failure("preflight", "releases are cut from main")
    if run("preflight", ["git", "status", "--porcelain"]):
        raise Failure("preflight", "the working tree is not clean")
    run("preflight", ["git", "fetch", "--tags", "origin"])
    if run("preflight", ["git", "rev-list", "--left-right", "--count", "HEAD...origin/main"]).split() != ["0", "0"]:
        raise Failure("preflight", "main differs from origin/main; pull or push first")
    current = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["poetry"]["version"]
    changelog = (ROOT / "CHANGELOG.md").read_text()
    sections = changelog_sections(changelog)
    unreleased = sections.get("Unreleased")
    if unreleased is None:
        raise Failure("preflight", "CHANGELOG.md has no [Unreleased] section")
    prepared = current == version and version in sections
    if run("preflight", ["git", "tag", "--list", f"v{version}"]):
        if not prepared or run("preflight", ["git", "rev-list", "-n", "1", f"v{version}"]) != run("preflight", ["git", "rev-parse", "HEAD"]):
            raise Failure("preflight", f"tag v{version} already exists and is not this prepared commit")
    if prepared:
        if unreleased.strip():
            raise Failure("preflight", f"{version} is already in CHANGELOG.md, but [Unreleased] is not empty")
    else:
        if parse_version(version) <= parse_version(current):
            raise Failure("preflight", f"{version} is not above the current version {current}")
        if not unreleased.strip():
            raise Failure("preflight", "[Unreleased] in CHANGELOG.md is empty; describe the release there first")
    return current, prepared


def checks():
    run("checks", ["poetry", "install", "--quiet"])
    run("checks", ["poetry", "run", "pytest", "-q", "-p", "no:cacheprovider"])
    run("checks", ["poetry", "run", "mermaid-comb", "setup"])
    run("checks", ["poetry", "run", "mermaid-comb", "parity"])


def prepare(version):
    run("prepare", ["poetry", "version", version])
    path = ROOT / "CHANGELOG.md"
    text = path.read_text()
    today = datetime.date.today().isoformat()
    text = text.replace("## [Unreleased]\n", f"## [Unreleased]\n\n## [{version}] - {today}\n", 1)
    path.write_text(re.sub(r"\n{3,}", repl="\n\n", string=text))
    run("prepare", ["git", "add", "pyproject.toml", "CHANGELOG.md"])
    run("prepare", ["git", "commit", "-m", f"Release {version}"])


def publish(version):
    notes = release_notes((ROOT / "CHANGELOG.md").read_text(), version=version)
    if not notes:
        raise Failure("publish", f"CHANGELOG.md has no notes under [{version}]")
    if not run("publish", ["git", "tag", "--list", f"v{version}"]):
        run("publish", ["git", "tag", "-a", f"v{version}", "-m", f"Mermaid's Comb {version}"])
    run("publish", ["git", "push", "origin", "main", f"v{version}"])
    existing = subprocess.run(["gh", "release", "view", f"v{version}", "--repo", REPOSITORY], cwd=ROOT, capture_output=True, text=True)
    if existing.returncode != 0:
        run("publish", ["gh", "release", "create", f"v{version}", "--repo", REPOSITORY, "--title", f"Mermaid's Comb {version}", "--notes", notes, "--verify-tag"])


def verify(version):
    reported = run("verify", ["uvx", "--refresh", "--from", f"git+https://github.com/{REPOSITORY}@v{version}", "mermaid-comb", "--version"])
    if not reported.endswith(f"version {version}"):
        raise Failure("verify", f"the tagged install reports `{reported}`, expected version {version}")
    return reported


def main():
    parser = argparse.ArgumentParser(description="Cut a Mermaid's Comb release: checks, version and changelog, tag, GitHub release, install check.")
    parser.add_argument("version", help="the new version, MAJOR.MINOR.PATCH")
    parser.add_argument("--dry-run", action="store_true", help="run the preflight and the checks only; change nothing")
    args = parser.parse_args()
    try:
        current, prepared = preflight(args.version)
        print(f"preflight: releasing {args.version} (pyproject says {current}; {'already prepared' if prepared else 'will move [Unreleased]'})", flush=True)
        checks()
        print("checks: tests and parity passed", flush=True)
        if args.dry_run:
            print("dry run: nothing changed")
            return
        if not prepared:
            prepare(args.version)
            print(f"prepare: committed Release {args.version}", flush=True)
        publish(args.version)
        print(f"publish: pushed v{args.version} and created its GitHub release", flush=True)
        print(f"verify: {verify(args.version)}")
    except Failure as failure:
        print(f"release {failure.phase} failed: {failure}", file=sys.stderr)
        sys.exit(EXIT[failure.phase])


if __name__ == "__main__":
    main()
