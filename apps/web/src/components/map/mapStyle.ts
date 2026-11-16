import type { StyleSpecification } from "maplibre-gl";

/**
 * Fond de carte sans tiers : contours des communes et des IRIS servis par NOTRE Martin
 * (gold.dim_commune, gold.dim_iris ; IGN-INSEE Contours IRIS, Licence Ouverte), proxifiés
 * par Next sous /tiles. Aucun fond OSM ni clé : hors de la Gironde relevée, la carte
 * reste noire. Pas de couche de texte : aucune police à télécharger.
 */
export const SOL_COLORS = {
  forte: "#4a3324",
  moyenne: "#2a231f",
} as const;

export function atlasStyle(origin: string): StyleSpecification {
  const tiles = (src: string): string[] => [`${origin}/tiles/${src}/{z}/{x}/{y}`];
  return {
    version: 8,
    sources: {
      communes: { type: "vector", tiles: tiles("communes"), minzoom: 0, maxzoom: 14 },
      iris: { type: "vector", tiles: tiles("iris"), minzoom: 0, maxzoom: 14 },
    },
    layers: [
      { id: "fond", type: "background", paint: { "background-color": "#05070a" } },
      {
        id: "terre",
        type: "fill",
        source: "communes",
        "source-layer": "communes",
        paint: { "fill-color": "#101622" },
      },
      {
        id: "sol-argiles",
        type: "fill",
        source: "iris",
        "source-layer": "iris",
        filter: ["in", ["get", "rga_exposition"], ["literal", ["Exposition forte", "Exposition moyenne"]]],
        paint: {
          "fill-color": ["match", ["get", "rga_exposition"], "Exposition forte", SOL_COLORS.forte, SOL_COLORS.moyenne],
          "fill-opacity": 0.9,
        },
      },
      {
        id: "sol-inconnu",
        type: "fill",
        source: "iris",
        "source-layer": "iris",
        filter: ["==", ["get", "rga_exposition"], "inconnu"],
        paint: { "fill-pattern": "hachures" },
      },
      {
        id: "iris-traits",
        type: "line",
        source: "iris",
        "source-layer": "iris",
        minzoom: 10,
        paint: { "line-color": "#2a3446", "line-width": 0.5 },
      },
      {
        id: "communes-traits",
        type: "line",
        source: "communes",
        "source-layer": "communes",
        paint: {
          "line-color": "#4a5568",
          "line-width": ["interpolate", ["linear"], ["zoom"], 7, 0.35, 11, 1, 14, 1.6],
          "line-opacity": 0.85,
        },
      },
    ],
  };
}

/** Motif de hachures (le « blanc » des cartographes) dessiné localement, sans image tierce. */
export function hatchImage(size = 12): { width: number; height: number; data: Uint8Array } {
  const data = new Uint8Array(size * size * 4);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const on = (x + y) % size === 0 || (x + y) % size === size - 1;
      const i = (y * size + x) * 4;
      data[i] = 236;
      data[i + 1] = 230;
      data[i + 2] = 214;
      data[i + 3] = on ? 70 : 0;
    }
  }
  return { width: size, height: size, data };
}

export const MAP_LOCALE: Record<string, string> = {
  "NavigationControl.ZoomIn": "Zoomer",
  "NavigationControl.ZoomOut": "Dézoomer",
  "NavigationControl.ResetBearing": "Remettre le nord en haut",
  "AttributionControl.ToggleAttribution": "Afficher ou masquer les crédits",
  "Map.Title": "Carte",
};
