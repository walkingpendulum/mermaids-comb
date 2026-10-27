---
name: release
description: "Cut a Mermaid's Comb release: choose the version from CHANGELOG.md's [Unreleased] entries, then run release.py, which checks main, runs the tests and parity, bumps pyproject.toml, dates the changelog section, tags vX.Y.Z, pushes, creates the GitHub release from the changelog and verifies that the tagged install reports the new version. Use whenever asked to release, tag, publish or ship a version of mermaid-comb, or to bump its version."
---

# Releasing Mermaid's Comb

A release is a tag `vX.Y.Z` on `main`, a GitHub release whose notes are that version's section of
`CHANGELOG.md`, and `pyproject.toml` at the same version. Users install a release with
`uv tool install git+https://github.com/walkingpendulum/mermaids-comb@vX.Y.Z`. There is no PyPI
package.

## 1. Write the changelog entry

Every change a user can notice goes under `## [Unreleased]` in `CHANGELOG.md` as it lands:
one bullet per change, starting with the command or file it affects (`` `mermaid-comb solve`: ``),
saying what a user sees, not how the code changed. Before a release, read the section against
`git log v<last>..main --oneline` and add anything missing.

## 2. Choose the version

Read `[Unreleased]` and apply the rule stated at the top of `CHANGELOG.md`:

| The entries contain | Bump |
|---|---|
| a removed or renamed command or option, a changed exit code, output a script could no longer parse | major (minor while the version is 0.x) |
| a new command or option, new behaviour, a newer pinned Mermaid, dagre-d3-es or Puppeteer | minor |
| fixes only | patch |

A Mermaid upgrade also needs the steps in `VENDORED.md` done and `mermaid-comb parity` passing
before the release.

## 3. Run the release

From the repository root:

```bash
poetry run python .claude/skills/release/release.py X.Y.Z --dry-run   # preflight and checks only
poetry run python .claude/skills/release/release.py X.Y.Z
```

It refuses to start unless `main` is checked out, clean and level with `origin/main`, the tag does
not exist, and the version is above `pyproject.toml`'s with a non-empty `[Unreleased]`. When
`pyproject.toml` already has the version and `CHANGELOG.md` already has its section (a first
release, or a rerun after a failed publish), it skips the bump and publishes as is. Then it runs
the tests and `mermaid-comb parity`, commits `Release X.Y.Z`, tags, pushes, creates the GitHub
release and installs the tag with `uvx` to check `mermaid-comb --version`.

## 4. When it stops

| Exit | Phase | What to do |
|---|---|---|
| 2 | usage | pass a `MAJOR.MINOR.PATCH` version |
| 3 | preflight | fix what it names (checkout, commit or pull, fill `[Unreleased]`); nothing was changed |
| 4 | checks | a test or parity failed; fix it on `main` first; nothing was changed |
| 5 | prepare | the bump or the release commit failed; inspect with `git status` and `git log -1`, undo a local release commit with `git reset --hard origin/main` only when it was not pushed |
| 6 | publish | read which command failed and fix its cause (authentication, network); rerun the same command: it resumes from the existing release commit and tag and creates only what is missing |
| 7 | verify | the release is out but the tagged install reports another version; report it to the user before anything else |

## Never without the user's explicit go-ahead

Move, delete or recreate a pushed tag; delete or edit a published GitHub release; force-push
`main`; release from a branch other than `main`.
