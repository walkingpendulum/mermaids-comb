# Changelog

## 0.1.0

First release.

- `mermaid-comb solve`: an exact layered layout (OR-Tools CP-SAT) under Mermaid's subgraph rules,
  forced onto dagre through link lengths, declaration order and, when needed, one commented
  invisible edge; label collisions repaired against real renders. The diagram's meaning is
  checked unchanged before writing.
- `mermaid-comb check`: crossings, edges under nodes and edge-label collisions of a `.mmd` or
  `.svg`.
- `mermaid-comb setup`: installs Mermaid 11.16.0, dagre-d3-es 7.0.14, Puppeteer 25.2.1 and its
  headless Chrome into the user cache, and builds the traced Mermaid copy.
- `mermaid-comb parity`: checks the traced copy against the pristine Mermaid and the order replay
  against real renders.
