// Mesure le JavaScript initial réellement chargé par la page : scripts listés dans le HTML
// servi (serveur de production), taille gzip niveau 9. Budget : 200 kB (docs/plan-sprints.md).
// Usage : node scripts/bundle-budget.mjs [url]   (défaut http://127.0.0.1:3123/)
import { gzipSync } from "node:zlib";

const url = process.argv[2] ?? "http://127.0.0.1:3123/";
const BUDGET_KB = 200;
const html = await (await fetch(url)).text();
const srcs = [...html.matchAll(/<script[^>]+src="([^"]+)"/g)].map((m) => m[1]);
let raw = 0;
let gz = 0;
const rows = [];
for (const src of new Set(srcs)) {
  const buf = Buffer.from(await (await fetch(new URL(src, url))).arrayBuffer());
  const g = gzipSync(buf, { level: 9 }).length;
  raw += buf.length;
  gz += g;
  rows.push([src.split("/").pop(), (buf.length / 1024).toFixed(1), (g / 1024).toFixed(1)]);
}
const htmlGz = gzipSync(Buffer.from(html), { level: 9 }).length;
console.table(rows.map(([f, r, g]) => ({ fichier: f, "brut kB": r, "gzip kB": g })));
console.log(`HTML : ${(html.length / 1024).toFixed(1)} kB brut, ${(htmlGz / 1024).toFixed(1)} kB gzip`);
console.log(`JS initial : ${srcs.length} scripts, ${(raw / 1024).toFixed(1)} kB brut, ${(gz / 1024).toFixed(1)} kB gzip (budget ${BUDGET_KB} kB)`);
if (gz / 1024 > BUDGET_KB) {
  console.error("Budget de JS initial dépassé");
  process.exit(1);
}
