// Fails when the redesigned panel's first-load assets grow past the budget.
// Counts what dist/next/index.html loads before anything is lazy-loaded:
// the entry script, its modulepreload chunks and its stylesheets (gzip sizes).
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

const DIST = fileURLToPath(new URL("../dist/", import.meta.url));
const BUDGET = { js: 200 * 1024, css: 30 * 1024 };

const html = readFileSync(join(DIST, "next/index.html"), "utf8");
const refs = [...html.matchAll(/(?:src|href)="(\/assets\/[^"]+\.(js|css))"/g)].map((m) => ({ path: m[1], kind: m[2] }));
if (refs.length === 0) {
  console.error("No assets found in dist/next/index.html — was the build run?");
  process.exit(1);
}

const totals = { js: 0, css: 0 };
for (const ref of new Map(refs.map((r) => [r.path, r])).values()) {
  const size = gzipSync(readFileSync(join(DIST, ref.path.slice(1)))).length;
  totals[ref.kind] += size;
  console.log(`${(size / 1024).toFixed(1).padStart(7)} KB  ${ref.path}`);
}

let failed = false;
for (const kind of ["js", "css"]) {
  const ok = totals[kind] <= BUDGET[kind];
  failed ||= !ok;
  console.log(`${ok ? "ok  " : "FAIL"} ${kind}: ${(totals[kind] / 1024).toFixed(1)} KB gzip (budget ${BUDGET[kind] / 1024} KB)`);
}
process.exit(failed ? 1 : 0);
