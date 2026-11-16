/**
 * Données des hexagones pour la carte : cache des réponses /hex, union des années en
 * résolution 7 (pour que les hauteurs passent d'une année réelle à l'autre sans saut),
 * tuiles fixes de 0,5° en résolution 9. Aucun chiffre n'est créé : une cellule absente
 * d'une année n'a pas de valeur pour cette année (hauteur nulle, transparente).
 */
import { cellToBoundary, cellToLatLng } from "h3-js";
import { fetchHex, type HexQuery } from "./api";
import { GIRONDE_BBOX, r9Tiles, type Bbox } from "./geo";
import type { AnneeFiltre, DpeFiltre, HexCell, TypeFiltre } from "./types";

export const ANNEES: readonly AnneeFiltre[] = ["tous", "2021", "2022", "2023", "2024"];

export interface Valeur {
  p: number;
  n: number;
}

export interface HexDatum {
  h3: string;
  polygon: [number, number][];
  lon: number;
  lat: number;
  vals: Partial<Record<AnneeFiltre, Valeur>>;
}

const cache = new Map<string, Promise<HexCell[]>>();

export function cachedHex(q: HexQuery, signal?: AbortSignal): Promise<HexCell[]> {
  const key = JSON.stringify(q);
  const hit = cache.get(key);
  if (hit) return hit;
  const p = fetchHex(q, signal ? { signal } : undefined);
  cache.set(key, p);
  p.catch(() => cache.delete(key)); // un échec n'est jamais mis en cache
  return p;
}

const geomCache = new Map<string, Pick<HexDatum, "polygon" | "lon" | "lat">>();

function geom(h3: string): Pick<HexDatum, "polygon" | "lon" | "lat"> {
  const g = geomCache.get(h3);
  if (g) return g;
  const [lat, lon] = cellToLatLng(h3);
  const out = { polygon: cellToBoundary(h3, true) as [number, number][], lon, lat };
  geomCache.set(h3, out);
  return out;
}

/** Union par cellule des réponses de plusieurs années (fonction pure). */
export function unionByYear(byYear: ReadonlyArray<readonly [AnneeFiltre, readonly HexCell[]]>): HexDatum[] {
  const out = new Map<string, HexDatum>();
  for (const [annee, cells] of byYear) {
    for (const c of cells) {
      const prev = out.get(c.h3);
      const v = { p: c.prix_m2_median, n: c.n_ventes };
      out.set(c.h3, prev ? { ...prev, vals: { ...prev.vals, [annee]: v } } : { h3: c.h3, ...geom(c.h3), vals: { [annee]: v } });
    }
  }
  return [...out.values()].sort((a, b) => (a.h3 < b.h3 ? -1 : 1));
}

export async function loadR7(type: TypeFiltre, dpe: DpeFiltre, signal?: AbortSignal): Promise<HexDatum[]> {
  const results = await Promise.all(
    ANNEES.map(async (annee) => [annee, await cachedHex({ bbox: GIRONDE_BBOX, res: 7, type, dpe, annee }, signal)] as const),
  );
  return unionByYear(results);
}

export async function loadR9(view: Bbox, type: TypeFiltre, dpe: DpeFiltre, annee: AnneeFiltre, signal?: AbortSignal): Promise<HexDatum[]> {
  const tiles = r9Tiles(view);
  const parts = await Promise.all(tiles.map((bbox) => cachedHex({ bbox, res: 9, type, dpe, annee }, signal)));
  return unionByYear([[annee, parts.flat()]]);
}
