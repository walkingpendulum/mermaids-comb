import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import url from "node:url";

const here = path.dirname(url.fileURLToPath(import.meta.url));
const vendored = JSON.parse(fs.readFileSync(path.join(here, "vendored.json"), "utf8"));
const mermaidRoot = path.join(here, "node_modules", "mermaid");
const distDir = path.join(mermaidRoot, "dist");

const ORDER_CALL = '  time2("    order", () => order(g));\n';
const SNAPSHOT =
  "  globalThis.__dagrePre = { graph: JSON.parse(JSON.stringify(g.graph())), " +
  "nodes: g.nodes().map((v) => ({ v, value: JSON.parse(JSON.stringify(g.node(v) ?? {})), parent: g.parent(v) ?? null })), " +
  "edges: g.edges().map((e) => ({ v: e.v, w: e.w, name: e.name ?? null, value: JSON.parse(JSON.stringify(g.edge(e) ?? {})) })) };\n";
const RECORD =
  "  globalThis.__dagreTrace?.push({ pre: globalThis.__dagrePre, " +
  "edges: g.edges().map((e) => [e.v, e.w, e.name ?? null]), " +
  "nodes: g.nodes().map((v) => { const n = g.node(v); return { v, rank: n.rank, order: n.order, dummy: n.dummy ?? null, " +
  "parent: g.parent(v) ?? null, edge: n.edgeObj ? [n.edgeObj.v, n.edgeObj.w, n.edgeObj.name ?? null] : null, " +
  "borderType: n.borderType ?? null }; }) });\n";

const sha256 = (text) => crypto.createHash("sha256").update(text).digest("hex");

function dagreChunk() {
  const chunkDir = path.join(distDir, "chunks", "mermaid.esm");
  const matches = fs.readdirSync(chunkDir).filter((name) => name.endsWith(".mjs") && fs.readFileSync(path.join(chunkDir, name), "utf8").includes(ORDER_CALL));
  if (matches.length !== 1) throw new Error(`expected one Mermaid chunk containing dagre's order call, found ${matches.length}`);
  const text = fs.readFileSync(path.join(chunkDir, matches[0]), "utf8");
  if (text.split(ORDER_CALL).length !== 2) throw new Error(`dagre's order call is not unique in ${matches[0]}`);
  return { name: matches[0], text, patched: text.replace(ORDER_CALL, SNAPSHOT + ORDER_CALL + RECORD) };
}

function describe() {
  const installed = JSON.parse(fs.readFileSync(path.join(mermaidRoot, "package.json"), "utf8")).version;
  const chunk = dagreChunk();
  return { mermaid: installed, chunk: `chunks/mermaid.esm/${chunk.name}`, anchor: ORDER_CALL.trim(), pristineSha256: sha256(chunk.text), patchedSha256: sha256(chunk.patched) };
}

function build(target) {
  const found = describe();
  for (const key of ["mermaid", "chunk", "anchor", "pristineSha256", "patchedSha256"]) {
    if (found[key] !== vendored[key]) {
      throw new Error(`vendored.json says ${key} = ${vendored[key]}, the installed Mermaid gives ${found[key]}; follow VENDORED.md to update`);
    }
  }
  fs.rmSync(target, { recursive: true, force: true });
  fs.mkdirSync(target, { recursive: true });
  fs.cpSync(path.join(distDir, "mermaid.esm.mjs"), path.join(target, "mermaid.esm.mjs"));
  fs.cpSync(path.join(distDir, "chunks", "mermaid.esm"), path.join(target, "chunks", "mermaid.esm"), { recursive: true });
  fs.writeFileSync(path.join(target, vendored.chunk), dagreChunk().patched);
}

const [command, target] = process.argv.slice(2);
if (command === "describe") {
  process.stdout.write(JSON.stringify(describe(), null, 2) + "\n");
} else if (command === "build" && target) {
  build(target);
} else {
  process.stderr.write("usage: node trace_patch.mjs describe | build <target-dir>\n");
  process.exit(2);
}
