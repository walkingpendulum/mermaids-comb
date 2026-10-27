# Pinned Mermaid and the trace patch

Mermaid's Comb measures layouts with one exact build of Mermaid and reads dagre's internal layered
graph from it. This file records what is pinned, what is patched, and how to move to a newer
Mermaid.

## What is pinned

| Package | Version | Why |
|---|---|---|
| `mermaid` | 11.16.0 | renders every candidate layout; its bundled dagre decides ranks and order |
| `dagre-d3-es` | 7.0.14 | the same dagre Mermaid bundles, loaded unbundled so `order()` can be replayed in Node |
| `puppeteer` | 25.2.1 | drives the headless Chrome that renders; it pins that Chrome build |

The exact tree is in [`mermaid_comb/js/package-lock.json`](mermaid_comb/js/package-lock.json).
`mermaid-comb setup` installs it with `npm ci` into
`$XDG_CACHE_HOME/mermaid-comb/runtime-<hash>` (default `~/.cache/...`), where the hash covers
every shipped file in `mermaid_comb/js/`. A new release of the tool therefore never reuses an old
runtime.

## What is patched

Mermaid's dagre copies the diagram into an internal layered graph, runs its phases, writes the
coordinates back and discards the copy. The solver needs that copy: each node's rank, the dummy
nodes of long edges and labels, the subgraph border nodes, and the graph exactly as dagre hands
it to its ordering phase. [`trace_patch.mjs`](mermaid_comb/js/trace_patch.mjs) inserts two
read-only snapshots around one line of the bundled dagre chunk:

```js
  time2("    order", () => order(g));
```

The first snapshot records the graph before `order()`; the second records each node's rank and
order after it. Nothing else changes. The patch is applied to a copy of `dist/mermaid.esm.mjs`
and `dist/chunks/mermaid.esm/` in the runtime's `traced/` directory; the installed package
stays pristine.

[`vendored.json`](mermaid_comb/js/vendored.json) records the facts the patch depends on, and
`setup` refuses to build when any of them differs:

| Key | Value for 11.16.0 |
|---|---|
| `mermaid` | `11.16.0` |
| `chunk` | `chunks/mermaid.esm/chunk-T5XCKZAJ.mjs` |
| `anchor` | `time2("    order", () => order(g));` |
| `pristineSha256` | `48219ef6bec401af331a2f8f819d61451ba7645d9b07532c4020c114bfcb4182` |
| `patchedSha256` | `51f4ccb37582e3c5f694d00ea122fe40cda5f90ad1cda4a0aecbd641b48448a8` |

## Updating to a newer Mermaid

1. In `mermaid_comb/js/package.json`, set the new `mermaid` version and the `dagre-d3-es`
   version that Mermaid release depends on (`npm view mermaid@<version> dependencies`).
   Regenerate the lock: `npm install --package-lock-only` in `mermaid_comb/js/`.
2. Install into a scratch directory and describe the patch target:

   ```bash
   mkdir /tmp/mc && cp mermaid_comb/js/{package.json,package-lock.json,trace_patch.mjs} /tmp/mc/
   echo '{}' > /tmp/mc/vendored.json && cd /tmp/mc && npm ci && node trace_patch.mjs describe
   ```

   If it reports that the order call is missing or not unique, dagre's code changed; update the
   anchor and the snapshot fields in `trace_patch.mjs` against the new chunk first.
3. Copy the printed `mermaid`, `chunk`, `anchor`, `pristineSha256` and `patchedSha256` into
   `mermaid_comb/js/vendored.json`.
4. Run `mermaid-comb setup`, then `mermaid-comb parity`. Parity must print `True` and `n/n` for
   every sample: the traced copy must render the same geometry as the pristine Mermaid, and the
   Node replay of `order()` must reproduce dagre's real ordering.
5. Run the test suite and re-solve the samples; record the version change in `CHANGELOG.md`.
