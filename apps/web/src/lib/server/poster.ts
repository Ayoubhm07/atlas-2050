import "server-only";
import { cellToBoundary } from "h3-js";
import { colorOf, hex, quantileBreaks } from "../ramp";
import type { HexCell } from "../types";

/**
 * Affiche du relevé : les hexagones r7 renvoyés par /hex, projetés côté serveur en SVG.
 * Les hexagones d'une même classe de prix sont fusionnés dans un seul tracé : 7 éléments
 * au lieu de 1 075.
 */
export const POSTER_W = 1600;

export interface PosterLayer {
  color: string;
  d: string;
}

export interface Poster {
  width: number;
  height: number;
  layers: PosterLayer[];
  breaks: number[];
  nCells: number;
  nVentes: number;
}

export function buildPoster(cells: readonly HexCell[]): Poster | null {
  if (cells.length === 0) return null;
  const rings = cells.map((c) => cellToBoundary(c.h3)); // [lat, lng][]
  let minLon = Infinity, maxLon = -Infinity, minLat = Infinity, maxLat = -Infinity;
  for (const ring of rings) for (const [lat, lon] of ring) {
    minLon = Math.min(minLon, lon); maxLon = Math.max(maxLon, lon);
    minLat = Math.min(minLat, lat); maxLat = Math.max(maxLat, lat);
  }
  const k = Math.cos((((minLat + maxLat) / 2) * Math.PI) / 180);
  const scale = POSTER_W / ((maxLon - minLon) * k);
  const height = Math.ceil((maxLat - minLat) * scale);
  const breaks = quantileBreaks(cells.map((c) => c.prix_m2_median));
  const groups = new Map<string, PosterLayer>();
  cells.forEach((c, i) => {
    const ring = rings[i] ?? [];
    const pts = ring.map(([lat, lon]) => [Math.round((lon - minLon) * k * scale), Math.round((maxLat - lat) * scale)] as const);
    const color = hex(colorOf(c.prix_m2_median, breaks));
    const key = color;
    // tracé relatif : premier point absolu, puis petits déplacements (2 à 3 fois plus court)
    const d = `M${pts[0]?.[0] ?? 0} ${pts[0]?.[1] ?? 0}${pts
      .slice(1)
      .map((q, j) => `l${q[0] - (pts[j]?.[0] ?? 0)} ${q[1] - (pts[j]?.[1] ?? 0)}`)
      .join("")}z`;
    const g = groups.get(key);
    groups.set(key, g ? { ...g, d: g.d + d } : { color, d });
  });
  return {
    width: POSTER_W,
    height,
    layers: [...groups.values()],
    breaks,
    nCells: cells.length,
    nVentes: cells.reduce((s, c) => s + c.n_ventes, 0),
  };
}
