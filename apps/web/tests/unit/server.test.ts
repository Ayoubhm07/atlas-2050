import path from "node:path";
import { describe, expect, it } from "vitest";
import { loadMethodFigures } from "@/lib/server/method";
import { buildPoster } from "@/lib/server/poster";

describe("chiffres de méthode lus dans ml/results.json", () => {
  it("correspondent au rapport du modèle (aucune saisie à la main)", () => {
    const m = loadMethodFigures(path.join(__dirname, "..", "..", "..", "..", "ml", "results.json"));
    expect(m.nVentes).toBe(78358);
    expect(Math.round(m.maeTemporel)).toBe(726);
    expect(Math.round(m.maeSpatial)).toBe(871);
    expect(m.partDpe).toBeCloseTo(7.5, 1);
    expect(m.porte).toBe(true);
    expect(m.risques.map((r) => r.term)).toEqual(["ppri", "in_tri", "catnat_3plus", "rga_forte"]);
  });
});

describe("affiche SVG", () => {
  it("fusionne par bande et par classe, compte les ventes", () => {
    const cells = [
      { h3: "871f8c0a9ffffff", n_ventes: 20, prix_m2_median: 3000 },
      { h3: "871f8c0abffffff", n_ventes: 9, prix_m2_median: 2500 },
      { h3: "871f8c0a8ffffff", n_ventes: 7, prix_m2_median: 5200 },
    ];
    const p = buildPoster(cells);
    expect(p?.nCells).toBe(3);
    expect(p?.nVentes).toBe(36);
    expect(p?.layers.length).toBeLessThanOrEqual(3);
    for (const l of p?.layers ?? []) expect(l.d).toMatch(/^(M-?\d+ -?\d+(l-?\d+ -?\d+)+z)+$/);
    expect(buildPoster([])).toBeNull();
  });
});
