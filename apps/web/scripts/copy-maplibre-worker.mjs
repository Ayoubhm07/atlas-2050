// MapLibre 6 charge son worker à côté de son module (import.meta.url) : une fois le
// module empaqueté par Next, ce chemin n'existe plus. On sert le worker depuis public/,
// sous un nom versionné (cache immuable), et MapView le déclare avec setWorkerUrl.
import { copyFileSync, mkdirSync, readFileSync } from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const pkg = JSON.parse(readFileSync(path.join(root, "node_modules/maplibre-gl/package.json"), "utf-8"));
const dest = path.join(root, "public/vendor");
mkdirSync(dest, { recursive: true });
const name = `maplibre-gl-worker-${pkg.version}.mjs`;
copyFileSync(path.join(root, "node_modules/maplibre-gl/dist/maplibre-gl-worker.mjs"), path.join(dest, name));
console.log(`worker MapLibre copié : public/vendor/${name}`);
