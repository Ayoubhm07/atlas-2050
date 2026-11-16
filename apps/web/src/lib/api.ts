/**
 * Client de l'API locale. Dans le navigateur, tout passe par `/api/atlas` (réécriture
 * Next vers l'API : même origine, pas de CORS). Une adresse ne part jamais dans une URL :
 * elle voyage dans le corps d'un POST /estimate (docs/api/README.md).
 */
import {
  asCommuneHits,
  asCommuneRisques,
  asCommuneStats,
  asEstimation,
  asHexCells,
  ShapeError,
} from "./guards";
import type {
  AnneeFiltre,
  Bien,
  CommuneHit,
  CommuneRisques,
  CommuneStats,
  DpeFiltre,
  Envelope,
  Estimation,
  HexCell,
  Position,
  TypeFiltre,
} from "./types";

export const BROWSER_BASE = "/api/atlas";

export class ApiError extends Error {
  readonly status: number;
  readonly retryAfterS: number | null;
  constructor(status: number, message: string, retryAfterS: number | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.retryAfterS = retryAfterS;
  }
}

/** Message affichable pour toute erreur (réseau, API, forme inattendue). */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 429) {
      const wait = err.retryAfterS ? ` dans ${err.retryAfterS} s` : " dans un instant";
      return `Trop de demandes en peu de temps (limite de l'API). Réessayer${wait}.`;
    }
    return err.message;
  }
  if (err instanceof ShapeError) return err.message;
  if (err instanceof DOMException && err.name === "AbortError") return "Demande annulée.";
  if (err instanceof DOMException && err.name === "TimeoutError") {
    return "L'API locale ne répond pas à temps. Vérifier qu'elle tourne (make api-run).";
  }
  return "L'API locale est injoignable. Vérifier qu'elle tourne (make api-run).";
}

interface RequestOpts {
  signal?: AbortSignal;
  base?: string;
  init?: RequestInit;
  timeoutMs?: number;
}

async function request<T>(path: string, parse: (v: unknown) => T, opts: RequestOpts = {}): Promise<T> {
  const base = opts.base ?? BROWSER_BASE;
  const timeout = AbortSignal.timeout(opts.timeoutMs ?? 15_000);
  const signal = opts.signal ? AbortSignal.any([opts.signal, timeout]) : timeout;
  const res = await fetch(`${base}${path}`, { ...opts.init, signal, headers: { Accept: "application/json", ...opts.init?.headers } });
  let body: Envelope<unknown> | null = null;
  try {
    body = (await res.json()) as Envelope<unknown>;
  } catch {
    body = null;
  }
  if (!res.ok || !body || body.success !== true) {
    const retry = Number(res.headers.get("Retry-After"));
    const message = body?.error ?? `Erreur ${res.status} de l'API locale`;
    throw new ApiError(res.status, message, Number.isFinite(retry) && retry > 0 ? retry : null);
  }
  return parse(body.data);
}

export interface HexQuery {
  bbox: readonly [number, number, number, number];
  res: 7 | 9;
  type: TypeFiltre;
  dpe: DpeFiltre;
  annee: AnneeFiltre;
}

export function hexPath(q: HexQuery): string {
  const bbox = q.bbox.map((v) => Number(v.toFixed(4))).join(",");
  const p = new URLSearchParams({ bbox, res: String(q.res), type: q.type, dpe: q.dpe, annee: q.annee });
  return `/hex?${p.toString()}`;
}

export function fetchHex(q: HexQuery, opts?: RequestOpts): Promise<HexCell[]> {
  return request(hexPath(q), asHexCells, opts);
}

export function searchCommunes(q: string, opts?: RequestOpts): Promise<CommuneHit[]> {
  return request(`/communes?q=${encodeURIComponent(q)}`, asCommuneHits, opts);
}

export function fetchCommuneStats(code: string, opts?: RequestOpts): Promise<CommuneStats> {
  return request(`/communes/${encodeURIComponent(code)}/stats`, asCommuneStats, opts);
}

export function fetchCommuneRisques(code: string, opts?: RequestOpts): Promise<CommuneRisques> {
  return request(`/communes/${encodeURIComponent(code)}/risques`, asCommuneRisques, opts);
}

/** Corps commun du bien, sans champ vide (l'API rejette les valeurs hors domaine). */
export function bienParams(b: Bien): Record<string, string | number> {
  const out: Record<string, string | number> = {
    type_local: b.type_local,
    surface: b.surface,
    pieces: b.pieces,
    dependances: b.dependances,
  };
  if (b.type_local === "Maison" && b.surface_terrain !== null) out.surface_terrain = b.surface_terrain;
  if (b.dpe) out.dpe = b.dpe;
  return out;
}

export function estimate(bien: Bien, pos: Position, opts?: RequestOpts): Promise<Estimation> {
  const timeoutMs = opts?.timeoutMs ?? 20_000;
  if (pos.kind === "point") {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries({ ...bienParams(bien), lat: pos.lat.toFixed(6), lon: pos.lon.toFixed(6) })) {
      p.set(k, String(v));
    }
    return request(`/estimate?${p.toString()}`, asEstimation, { ...opts, timeoutMs });
  }
  return request("/estimate", asEstimation, {
    ...opts,
    timeoutMs,
    init: {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...bienParams(bien), address: pos.address }),
    },
  });
}
