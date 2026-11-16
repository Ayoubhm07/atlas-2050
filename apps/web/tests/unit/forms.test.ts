import { describe, expect, it } from "vitest";
import { DEFAULT_DRAFT, validateDraft } from "@/components/estimate/BienForm";
import { EMPTY_POSITION, resolvePosition } from "@/components/estimate/PositionPicker";
import { unionByYear } from "@/lib/hexdata";

describe("formulaire du bien (mêmes bornes que l'API)", () => {
  it("accepte les valeurs par défaut", () => {
    const v = validateDraft(DEFAULT_DRAFT);
    expect(v.bien).toEqual({ type_local: "Maison", surface: 96, pieces: 4, surface_terrain: 500, dependances: 0, dpe: null });
  });
  it("refuse un terrain de plus d'un hectare et une surface hors domaine", () => {
    const v = validateDraft({ ...DEFAULT_DRAFT, surface_terrain: "12000", surface: "5" });
    expect(v.bien).toBeNull();
    expect(v.errors.surface_terrain).toMatch(/hectare/);
    expect(v.errors.surface).toBeDefined();
  });
  it("accepte la virgule décimale, ignore le terrain d'un appartement", () => {
    const v = validateDraft({ ...DEFAULT_DRAFT, type_local: "Appartement", surface: "45,5", surface_terrain: "999999" });
    expect(v.bien?.surface).toBe(45.5);
    expect(v.bien?.surface_terrain).toBeNull();
  });
});

describe("position", () => {
  it("adresse trop courte, commune non choisie, point de carte", () => {
    expect(resolvePosition({ ...EMPTY_POSITION, address: "ab" }).ok).toBe(false);
    expect(resolvePosition({ ...EMPTY_POSITION, mode: "commune" }).ok).toBe(false);
    const r = resolvePosition({ ...EMPTY_POSITION, mode: "carte", point: { lat: 44.8, lon: -0.5, label: "p" } });
    expect(r).toEqual({ ok: true, pos: { kind: "point", lat: 44.8, lon: -0.5, label: "p" } });
  });
});

describe("union des années (aucune valeur créée)", () => {
  it("une cellule absente d'une année n'a pas de valeur pour cette année", () => {
    const a = "871f8c0a9ffffff";
    const b = "871f8c0abffffff";
    const out = unionByYear([
      [
        "tous",
        [
          { h3: a, n_ventes: 20, prix_m2_median: 3000 },
          { h3: b, n_ventes: 9, prix_m2_median: 2500 },
        ],
      ],
      ["2024", [{ h3: a, n_ventes: 6, prix_m2_median: 3100 }]],
    ]);
    expect(out).toHaveLength(2);
    const ca = out.find((d) => d.h3 === a);
    const cb = out.find((d) => d.h3 === b);
    expect(ca?.vals).toEqual({ tous: { p: 3000, n: 20 }, "2024": { p: 3100, n: 6 } });
    expect(cb?.vals["2024"]).toBeUndefined();
    expect(ca?.polygon.length).toBeGreaterThanOrEqual(6);
  });
});
