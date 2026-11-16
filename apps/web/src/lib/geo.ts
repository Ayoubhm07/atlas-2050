/** Emprise de la Gironde (seul département ingéré, docs/methodology.md §4.6). */
export const GIRONDE_BBOX = [-1.3, 44.18, 0.34, 45.6] as const;
export const GIRONDE_CENTER = { lon: -0.58, lat: 44.85 } as const;

/** Tuiles fixes de 0,5° pour la résolution 9 (aire 0,25 deg², plafond de l'API). */
export const R9_TILE = 0.5;
export const R9_MIN_ZOOM = 10.5;

export type Bbox = readonly [number, number, number, number];

export function r9Tiles(view: Bbox): Bbox[] {
  const [xmin, ymin, xmax, ymax] = view;
  const out: Bbox[] = [];
  const x0 = Math.floor(Math.max(xmin, GIRONDE_BBOX[0]) / R9_TILE) * R9_TILE;
  const y0 = Math.floor(Math.max(ymin, GIRONDE_BBOX[1]) / R9_TILE) * R9_TILE;
  const x1 = Math.min(xmax, GIRONDE_BBOX[2]);
  const y1 = Math.min(ymax, GIRONDE_BBOX[3]);
  for (let x = x0; x < x1; x += R9_TILE) {
    for (let y = y0; y < y1; y += R9_TILE) {
      const r = (v: number): number => Math.round(v * 1000) / 1000;
      out.push([r(x), r(y), r(x + R9_TILE), r(y + R9_TILE)]);
    }
  }
  return out;
}
