import "server-only";
import { fetchHex } from "../api";
import { GIRONDE_BBOX } from "../geo";
import type { HexCell } from "../types";

const SERVER_BASE = process.env.ATLAS_API_URL ?? "http://127.0.0.1:8000";

export type Loaded<T> = { ok: true; data: T } | { ok: false; error: string };

/** Hexagones r7 de toute la Gironde (toutes années, tous types), pour l'affiche. */
export async function loadGirondeHex(): Promise<Loaded<HexCell[]>> {
  try {
    const data = await fetchHex(
      { bbox: GIRONDE_BBOX, res: 7, type: "tous", dpe: "tous", annee: "tous" },
      { base: SERVER_BASE, timeoutMs: 8_000, init: { next: { revalidate: 600 } } as RequestInit },
    );
    return { ok: true, data };
  } catch {
    return { ok: false, error: "API locale injoignable au rendu de la page (make api-run, puis recharger)." };
  }
}
