import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { asCommuneStats, asEstimation, asHexCells, ShapeError } from "@/lib/guards";
import { coordonnees, deNom, euros, eurosM2, fourchetteEuros, pctSigne } from "@/lib/format";
import { r9Tiles, GIRONDE_BBOX } from "@/lib/geo";
import { classOf, colorOf, legend, quantileBreaks, RAMP } from "@/lib/ramp";
import { domaine, ecartMedianes, groupScenarios, valeurFacteur, waterfall } from "@/lib/scenarios";
import type { Estimation } from "@/lib/types";

const fixture = (name: string): Estimation => {
  const raw = JSON.parse(readFileSync(path.join(__dirname, "..", "fixtures", `${name}.json`), "utf-8")) as { data: unknown };
  return asEstimation(raw.data);
};

describe("format (français, sans tiret cadratin)", () => {
  it("formate euros, €/m² et pourcentages signés", () => {
    expect(euros(549000)).toBe("549 000 €");
    expect(eurosM2(5720)).toBe("5 720 €/m²");
    expect(pctSigne(22.5)).toBe("+22,5 %");
    expect(pctSigne(-3.6)).toBe("−3,6 %");
    expect(fourchetteEuros(361000, 747000)).toMatch(/^de 361.000.€ à 747.000.€$/);
    expect(coordonnees(44.8378, -0.5792)).toBe("44,8378 N, 0,5792 O");
  });
  it("élide « de » devant une voyelle ou un h", () => {
    expect(deNom("Bordeaux")).toBe("de Bordeaux");
    expect(deNom("Arcachon")).toBe("d'Arcachon");
    expect(deNom("Hourtin")).toBe("d'Hourtin");
    expect(deNom("Étauliers")).toBe("d'Étauliers");
  });
  it("n'emploie jamais de tiret cadratin", () => {
    for (const s of [fourchetteEuros(1, 2), pctSigne(-1), coordonnees(1, 1)]) expect(s).not.toMatch(/—/);
  });
});

describe("rampe et classes", () => {
  it("bornes par quantiles croissantes et arrondies à 10 €", () => {
    const b = quantileBreaks([1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000]);
    expect(b.length).toBeLessThanOrEqual(RAMP.length - 1);
    expect([...b].sort((x, y) => x - y)).toEqual(b);
    b.forEach((v) => expect(v % 10).toBe(0));
  });
  it("classe et couleur aux extrémités", () => {
    const b = [2000, 3000];
    expect(classOf(100, b)).toBe(0);
    expect(classOf(2000, b)).toBe(1);
    expect(classOf(9000, b)).toBe(2);
    expect(colorOf(9000, b)).toEqual(RAMP[RAMP.length - 1]);
    expect(colorOf(100, b)).toEqual(RAMP[0]);
  });
  it("légende lisible", () => {
    const items = legend([2000, 3000], (n) => String(n));
    expect(items.map((i) => i.label)).toEqual(["moins de 2000", "de 2000 à 3000", "3000 et plus"]);
    expect(quantileBreaks([])).toEqual([]);
  });
});

describe("tuiles r9 de 0,5° (aire = plafond de l'API)", () => {
  it("couvrent la vue, restent dans la Gironde, aire 0,25 deg²", () => {
    expect(r9Tiles([-0.65, 44.8, -0.5, 44.9])).toEqual([[-1, 44.5, -0.5, 45]]);
    const all = r9Tiles(GIRONDE_BBOX);
    expect(all.length).toBe(16);
    for (const [x0, y0, x1, y1] of all) expect((x1 - x0) * (y1 - y0)).toBeCloseTo(0.25, 9);
  });
});

describe("garde-fous de forme (frontière réseau)", () => {
  it("refuse un hexagone sous 5 ventes (ADR 0005)", () => {
    expect(() => asHexCells([{ h3: "x", n_ventes: 4, prix_m2_median: 1000 }])).toThrow(ShapeError);
    expect(asHexCells([{ h3: "x", n_ventes: 5, prix_m2_median: 1000 }])).toHaveLength(1);
  });
  it("refuse un scénario DRIAS qui porterait un chiffre", () => {
    const est = fixture("estimate-bordeaux-maison-g");
    const bad = {
      ...est,
      scenarios: est.scenarios.map((s) => (s.id === "climat_rcp85" ? { ...s, prix_m2: { p10: 1, p50: 2, p90: 3 } } : s)),
    };
    expect(() => asEstimation(bad)).toThrow(ShapeError);
  });
  it("refuse une fourchette désordonnée et un groupe de moins de 5 ventes", () => {
    const est = fixture("estimate-bordeaux-maison-g");
    expect(() => asEstimation({ ...est, prix_m2: { p10: 3, p50: 2, p90: 1 } })).toThrow(ShapeError);
    const groupe = { type_local: "Maison", annee: 2024, n_ventes: 3, prix_m2_median: 1, prix_m2_q1: null, prix_m2_q3: null, surface_mediane: 90 };
    expect(() => asCommuneStats({ code_insee: "33063", groupes: [groupe] })).toThrow(ShapeError);
  });
});

describe("scénarios réels renvoyés par l'API", () => {
  it("Bordeaux, maison G : risques déjà présents, climat indisponible sans chiffre", () => {
    const g = groupScenarios(fixture("estimate-bordeaux-maison-g"));
    expect(g.statuQuo?.statut).toBe("calcule");
    expect(g.renovation?.statut).toBe("calcule");
    expect(g.sensibilites).toHaveLength(0);
    expect(g.dejaPresents.length).toBe(4);
    expect(g.climat.map((c) => c.statut)).toEqual(["indisponible (DRIAS)", "indisponible (DRIAS)"]);
    g.climat.forEach((c) => expect(c.prix_m2).toBeNull());
  });
  it("Arcachon, maison E : sensibilités non causales à deux bornes", () => {
    const g = groupScenarios(fixture("estimate-arcachon-maison-e"));
    expect(g.sensibilites.length).toBeGreaterThan(0);
    for (const s of g.sensibilites) {
      expect(s.libelle).toMatch(/non causal/);
      expect(s.sensibilite?.avec_voisinage).toBeDefined();
      expect(s.sensibilite?.sans_voisinage).toBeDefined();
    }
  });
  it("écart des médianes", () => {
    expect(ecartMedianes({ p10: 1, p50: 200, p90: 3 }, { p10: 1, p50: 150, p90: 3 })).toBeCloseTo(-25);
    expect(ecartMedianes({ p10: 0, p50: 0, p90: 0 }, { p10: 1, p50: 1, p90: 1 })).toBe(0);
  });
  it("le waterfall se referme sur la prédiction du modèle", () => {
    for (const name of ["estimate-bordeaux-maison-g", "estimate-arcachon-maison-e"]) {
      const est = fixture(name);
      const { steps, ecartArrondi } = waterfall(est.explication, est.facteurs);
      expect(steps[0]?.kind).toBe("base");
      expect(steps[steps.length - 1]?.to).toBe(est.explication.prix_m2_modele);
      expect(steps).toHaveLength(est.facteurs.length + 3);
      expect(Math.abs(ecartArrondi)).toBeLessThan(0.01 * est.explication.prix_m2_modele + 10);
    }
  });
  it("domaine commun avec marge, jamais négatif", () => {
    const [lo, hi] = domaine([{ p10: 100, p50: 200, p90: 300 }]);
    expect(lo).toBeLessThan(100);
    expect(lo).toBeGreaterThanOrEqual(0);
    expect(hi).toBeGreaterThan(300);
  });
  it("valeurs de facteurs : voisinage et position jamais affichés", () => {
    expect(valeurFacteur({ variable: "voisinage_log_prix", libelle: "", contribution_pct: 1, valeur: null })).toBeNull();
    expect(valeurFacteur({ variable: "log_surface", libelle: "", contribution_pct: 1, valeur: 96 })).toBe("96 m²");
    expect(valeurFacteur({ variable: "est_maison", libelle: "", contribution_pct: 1, valeur: 1 })).toBe("maison");
  });
});
