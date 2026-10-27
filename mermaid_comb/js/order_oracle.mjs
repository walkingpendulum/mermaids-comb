import path from "node:path";
import readline from "node:readline";
import url from "node:url";

const dagreSrc = path.join(path.dirname(url.fileURLToPath(import.meta.url)), "node_modules", "dagre-d3-es", "src");
const load = (relative) => import(url.pathToFileURL(path.join(dagreSrc, relative)).href);
const { Graph } = await load("graphlib/index.js");
const { order } = await load("dagre/order/index.js");

let loaded = null;

function reblock(items, key, order) {
  const slots = [];
  const blocks = new Map();
  items.forEach((item, i) => {
    const owner = key(item);
    if (owner === undefined) return;
    slots.push(i);
    if (!blocks.has(owner)) blocks.set(owner, []);
    blocks.get(owner).push(item);
  });
  const sequence = order.flatMap((owner) => blocks.get(owner) ?? []);
  if (sequence.length !== slots.length) throw new Error("edge order does not cover every dummy chain");
  const result = items.slice();
  slots.forEach((slot, i) => { result[slot] = sequence[i]; });
  return result;
}

function permuted(nodeOrder, edgeOrder) {
  const { pre, real, owner } = loaded;
  const byId = new Map(pre.nodes.map((n) => [n.v, n]));
  const nodes = pre.nodes.slice();
  const slots = [];
  nodes.forEach((n, i) => { if (real.has(n.v)) slots.push(i); });
  if (slots.length !== nodeOrder.length) throw new Error("node order does not match the loaded graph");
  slots.forEach((slot, i) => { nodes[slot] = byId.get(nodeOrder[i]); });
  const edgeOwner = (e) => owner.get(e.v) ?? owner.get(e.w);
  return {
    graph: pre.graph,
    nodes: reblock(nodes, (n) => owner.get(n.v), edgeOrder),
    edges: reblock(pre.edges, edgeOwner, edgeOrder),
  };
}

function rebuild(pre) {
  const g = new Graph({ directed: true, multigraph: true, compound: true });
  g.setGraph(pre.graph);
  for (const node of pre.nodes) g.setNode(node.v, node.value);
  for (const node of pre.nodes) if (node.parent !== null) g.setParent(node.v, node.parent);
  for (const edge of pre.edges) g.setEdge(edge.v, edge.w, edge.value, edge.name ?? undefined);
  return g;
}

function layering(g) {
  const layers = [];
  for (const v of g.nodes()) {
    const node = g.node(v);
    if (node.rank === undefined || g.children(v).length) continue;
    (layers[node.rank] ??= []).push(v);
  }
  return layers.map((layer) => (layer ?? []).sort((a, b) => g.node(a).order - g.node(b).order));
}

const lines = readline.createInterface({ input: process.stdin });
process.stdout.write(JSON.stringify({ ready: true }) + "\n");
for await (const line of lines) {
  if (!line.trim()) continue;
  const request = JSON.parse(line);
  try {
    if (request.load) {
      loaded = { pre: request.load.pre, real: new Set(request.load.real), owner: new Map(Object.entries(request.load.owner)) };
      process.stdout.write(JSON.stringify({ id: request.id, loaded: true }) + "\n");
      continue;
    }
    if (!loaded) throw new Error("no graph loaded");
    const g = rebuild(permuted(request.permute.nodes, request.permute.edges));
    order(g);
    process.stdout.write(JSON.stringify({ id: request.id, layering: layering(g) }) + "\n");
  } catch (error) {
    process.stdout.write(JSON.stringify({ id: request.id, error: String(error?.stack ?? error) }) + "\n");
  }
}
