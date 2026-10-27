import fs from "node:fs";
import path from "node:path";
import readline from "node:readline";
import url from "node:url";
import puppeteer from "puppeteer";

const here = path.dirname(url.fileURLToPath(import.meta.url));
const options = JSON.parse(process.argv[2] ?? "{}");
const ORIGIN = "https://mermaid-comb.invalid";
const mermaidDir = fs.realpathSync(options.mermaidDir);

function servedFile(requestUrl) {
  const file = fs.realpathSync(path.join(mermaidDir, decodeURIComponent(new URL(requestUrl).pathname)));
  if (path.relative(mermaidDir, file).startsWith("..")) throw new Error(`request outside the Mermaid directory: ${requestUrl}`);
  return file;
}

const pageUrl = url.pathToFileURL(path.join(here, "index.html")).href;

async function openPage(browser) {
  const page = await browser.newPage();
  await page.setViewport({ width: options.width, height: 600, deviceScaleFactor: options.scale });
  await page.setRequestInterception(true);
  page.on("request", (request) => {
    if (request.url() === pageUrl) return request.continue();
    if (new URL(request.url()).origin !== ORIGIN) return request.abort();
    try {
      const body = fs.readFileSync(servedFile(request.url()));
      return request.respond({ status: 200, headers: { "Access-Control-Allow-Origin": "*" }, contentType: "application/javascript", body });
    } catch (error) {
      process.stderr.write(`${error}\n`);
      return request.abort();
    }
  });
  await page.goto(pageUrl);
  await page.$eval("body", (body, color) => { body.style.background = color; }, options.background);
  await page.evaluate(async (entry) => {
    const { default: mermaid } = await import(entry);
    await Promise.all(Array.from(document.fonts, (font) => font.load()));
    window.__mermaid = mermaid;
  }, `${ORIGIN}/mermaid.esm.mjs`);
  return page;
}

async function render(page, definition) {
  return page.$eval(
    "#container",
    async (container, { definition, theme, background }) => {
      const mermaid = window.__mermaid;
      globalThis.__dagreTrace = [];
      mermaid.initialize({ startOnLoad: false, theme });
      const { svg: svgText } = await mermaid.render("my-svg", definition, container);
      container.innerHTML = svgText;
      const svg = container.getElementsByTagName("svg")[0];
      svg.style.backgroundColor = background;
      return { svg: new XMLSerializer().serializeToString(svg), trace: globalThis.__dagreTrace };
    },
    { definition, theme: options.theme, background: options.background },
  );
}

let browser;
try {
  browser = await puppeteer.launch({ headless: "shell" });
  const page = await openPage(browser);
  process.stdout.write(JSON.stringify({ ready: true }) + "\n");
  for await (const line of readline.createInterface({ input: process.stdin })) {
    if (!line.trim()) continue;
    const request = JSON.parse(line);
    try {
      const { svg, trace } = await render(page, request.text);
      process.stdout.write(JSON.stringify({ id: request.id, svg, trace }) + "\n");
    } catch (error) {
      process.stdout.write(JSON.stringify({ id: request.id, error: String(error?.message ?? error) }) + "\n");
    }
  }
} finally {
  await browser?.close();
}
