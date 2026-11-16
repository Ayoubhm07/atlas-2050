import { readFileSync } from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, bienParams, errorMessage, estimate, hexPath } from "@/lib/api";
import type { Bien } from "@/lib/types";

const BIEN: Bien = { type_local: "Maison", surface: 96, pieces: 4, surface_terrain: 500, dependances: 0, dpe: "G" };
const okBody = readFileSync(path.join(__dirname, "..", "fixtures", "estimate-bordeaux-maison-g.json"), "utf-8");

afterEach(() => vi.unstubAllGlobals());

describe("client de l'API locale", () => {
  it("chemin /hex arrondi et complet", () => {
    expect(hexPath({ bbox: [-1.123456, 44.1, 0.3, 45.6], res: 7, type: "tous", dpe: "tous", annee: "2024" })).toBe(
      "/hex?bbox=-1.1235%2C44.1%2C0.3%2C45.6&res=7&type=tous&dpe=tous&annee=2024",
    );
  });
  it("un appartement n'envoie pas de terrain, un DPE inconnu n'est pas envoyé", () => {
    expect(bienParams({ ...BIEN, type_local: "Appartement", dpe: null })).toEqual({
      type_local: "Appartement",
      surface: 96,
      pieces: 4,
      dependances: 0,
    });
  });
  it("une adresse part dans le corps d'un POST, jamais dans l'URL", async () => {
    const calls: { url: string; init: RequestInit | undefined }[] = [];
    vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      return new Response(okBody, { status: 200 });
    });
    await estimate(BIEN, { kind: "adresse", address: "12 cours de l'Intendance, Bordeaux" });
    expect(calls[0]?.url).toBe("/api/atlas/estimate");
    expect(calls[0]?.init?.method).toBe("POST");
    expect(String(calls[0]?.init?.body)).toMatch(/Intendance/);
  });
  it("coordonnées en GET", async () => {
    let seen = "";
    vi.stubGlobal("fetch", async (url: string) => {
      seen = url;
      return new Response(okBody, { status: 200 });
    });
    const est = await estimate(BIEN, { kind: "point", lat: 44.8378, lon: -0.5792, label: "x" });
    expect(seen).toMatch(/^\/api\/atlas\/estimate\?.*lat=44\.837800.*lon=-0\.579200/);
    expect(est.localisation.nom_commune).toBe("Bordeaux");
  });
  it("429 : message humain avec le délai de l'API", async () => {
    vi.stubGlobal(
      "fetch",
      async () =>
        new Response(JSON.stringify({ success: false, data: null, error: "Trop de requêtes", meta: {} }), {
          status: 429,
          headers: { "Retry-After": "12" },
        }),
    );
    const err = await estimate(BIEN, { kind: "point", lat: 1, lon: 1, label: "x" }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(errorMessage(err)).toMatch(/dans 12 s/);
  });
  it("erreur de l'API : son message est repris ; réseau coupé : message d'aide", async () => {
    vi.stubGlobal(
      "fetch",
      async () =>
        new Response(JSON.stringify({ success: false, data: null, error: "Point hors du périmètre couvert", meta: {} }), { status: 404 }),
    );
    const err = await estimate(BIEN, { kind: "point", lat: 1, lon: 1, label: "x" }).catch((e: unknown) => e);
    expect(errorMessage(err)).toBe("Point hors du périmètre couvert");
    expect(errorMessage(new TypeError("fetch failed"))).toMatch(/make api-run/);
  });
});
