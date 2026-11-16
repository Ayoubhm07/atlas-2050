import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchCommuneRisques, fetchCommuneStats, searchCommunes } from "@/lib/api";
import { asCommuneHits, asCommuneRisques, ShapeError } from "@/lib/guards";
import { cachedHex, loadR7, loadR9 } from "@/lib/hexdata";
import { createStore, nextNonce } from "@/lib/store";

const ok = (data: unknown): Response => new Response(JSON.stringify({ success: true, data, error: null, meta: { sources: [] } }), { status: 200 });

afterEach(() => vi.unstubAllGlobals());

describe("magasin partagé", () => {
  it("remplace l'état sans le muter et prévient les abonnés", () => {
    const s = createStore({ n: 1 });
    const first = s.get();
    const seen: number[] = [];
    const off = s.subscribe(() => seen.push(s.get().n));
    s.set((p) => ({ n: p.n + 1 }));
    s.set({ n: 5 });
    off();
    s.set({ n: 9 });
    expect(seen).toEqual([2, 5]);
    expect(first).toEqual({ n: 1 });
    expect(nextNonce()).toBeLessThan(nextNonce());
  });
});

describe("hexagones : cache, union des années, tuiles r9", () => {
  it("met une réponse en cache, jamais un échec", async () => {
    let calls = 0;
    vi.stubGlobal("fetch", async () => {
      calls += 1;
      return calls === 1 ? new Response("oups", { status: 503 }) : ok([{ h3: "871f8c0a9ffffff", n_ventes: 7, prix_m2_median: 3000 }]);
    });
    const q = { bbox: [0, 0, 0.1, 0.1] as const, res: 7 as const, type: "tous" as const, dpe: "tous" as const, annee: "2024" as const };
    await expect(cachedHex(q)).rejects.toBeTruthy();
    expect(await cachedHex(q)).toHaveLength(1);
    expect(await cachedHex(q)).toHaveLength(1);
    expect(calls).toBe(2);
  });
  it("r7 : cinq périodes réunies par cellule", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", async (url: string) => {
      urls.push(url);
      const annee = new URL(url, "http://x").searchParams.get("annee");
      return ok(annee === "2021" ? [] : [{ h3: "871f8c0a9ffffff", n_ventes: 9, prix_m2_median: annee === "tous" ? 3000 : 3100 }]);
    });
    const data = await loadR7("Maison", "C");
    expect(urls).toHaveLength(5);
    expect(urls.every((u) => u.includes("type=Maison") && u.includes("dpe=C") && u.includes("res=7"))).toBe(true);
    expect(data[0]?.vals.tous?.p).toBe(3000);
    expect(data[0]?.vals["2021"]).toBeUndefined();
  });
  it("r9 : une requête par tuile, doublons de bord fusionnés", async () => {
    const cell = { h3: "89184d99653ffff", n_ventes: 6, prix_m2_median: 4000 };
    vi.stubGlobal("fetch", async () => ok([cell]));
    const data = await loadR9([-0.6, 44.8, -0.4, 44.9], "tous", "tous", "2023");
    expect(data).toHaveLength(1);
    expect(data[0]?.vals["2023"]).toEqual({ p: 4000, n: 6 });
  });
});

describe("communes", () => {
  it("recherche, statistiques et risques passent par la frontière", async () => {
    vi.stubGlobal("fetch", async (url: string) => {
      if (url.includes("/stats")) return ok({ code_insee: "33009", groupes: [] });
      if (url.includes("/risques")) {
        return ok({ code_insee: "33009", nom_commune: "Arcachon", n_catnat_10ans: 2, in_tri: true, ppri: true, azi: null, rga_iris: null });
      }
      return ok([{ code_insee: "33009", nom_commune: "Arcachon", code_departement: "33", lon: -1.17, lat: 44.65 }]);
    });
    expect((await searchCommunes("Arca"))[0]?.nom_commune).toBe("Arcachon");
    expect((await fetchCommuneStats("33009")).groupes).toEqual([]);
    expect((await fetchCommuneRisques("33009")).rga_iris).toEqual({});
  });
  it("refuse des formes inattendues", () => {
    expect(() => asCommuneHits([{ code_insee: "33009" }])).toThrow(ShapeError);
    expect(() => asCommuneRisques({ code_insee: "33009" })).toThrow(ShapeError);
  });
});
