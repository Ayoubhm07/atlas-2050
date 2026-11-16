import "server-only";
import { readFileSync } from "node:fs";
import path from "node:path";

/**
 * Chiffres de la méthode lus dans ml/results.json (fichier généré par l'entraînement,
 * docs/methodology.md). Jamais saisis à la main : si le fichier change, la page suit.
 */
export interface MethodFigures {
  date: string;
  nVentes: number;
  nExcluesTerrain: number;
  nCommunes: number;
  annees: number[];
  nTrain: number;
  nTest: number;
  maeTemporel: number;
  mapeTemporel: number;
  r2Temporel: number;
  maeSpatial: number;
  mapeSpatial: number;
  r2Spatial: number;
  gainTemporel: { diff: number; low: number; high: number };
  gainSpatial: { diff: number; low: number; high: number };
  porte: boolean;
  nDpeApparies: number;
  partDpe: number;
  risques: { term: string; avec: number; sans: number }[];
}

type J = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

function num(v: unknown, what: string): number {
  if (typeof v !== "number" || !Number.isFinite(v)) throw new Error(`ml/results.json : ${what} manquant`);
  return v;
}

export function loadMethodFigures(file = path.join(process.cwd(), "..", "..", "ml", "results.json")): MethodFigures {
  const d = JSON.parse(readFileSync(/*turbopackIgnore: true*/ file, "utf-8")) as J;
  const t = d.temporel as J;
  const s = d.spatial as J;
  const e = d.effets as J;
  const factorPct = (x: J): number => (num(x.factor, "facteur de risque") - 1) * 100;
  const sans = new Map<string, number>((e.risques_sans_voisinage as J[]).map((x) => [String(x.term), factorPct(x)]));
  return {
    date: String(d.meta.date),
    nVentes: num(d.meta.n_ventes, "n_ventes"),
    nExcluesTerrain: num(d.meta.n_exclues_terrain, "n_exclues_terrain"),
    nCommunes: num(d.meta.n_communes, "n_communes"),
    annees: (d.meta.annees as unknown[]).map((a) => num(a, "année")),
    nTrain: num(t.n_train, "n_train"),
    nTest: num(t.n_test, "n_test"),
    maeTemporel: num(t.lgb.tous.mae, "MAE temporelle"),
    mapeTemporel: num(t.lgb.tous.mape, "MAPE temporelle") * 100,
    r2Temporel: num(t.lgb.tous.r2, "R² temporel"),
    maeSpatial: num(s.lgb.tous.mae, "MAE spatiale"),
    mapeSpatial: num(s.lgb.tous.mape, "MAPE spatiale") * 100,
    r2Spatial: num(s.lgb.tous.r2, "R² spatial"),
    gainTemporel: { diff: num(t.diff.diff, "écart"), low: num(t.diff.low, "IC bas"), high: num(t.diff.high, "IC haut") },
    gainSpatial: { diff: num(s.diff.diff, "écart"), low: num(s.diff.low, "IC bas"), high: num(s.diff.high, "IC haut") },
    porte: d.porte.passe === true,
    nDpeApparies: num(e.n_dpe_apparies, "DPE appariés"),
    partDpe: (num(e.n_dpe_apparies, "DPE appariés") / num(d.meta.n_ventes, "n_ventes")) * 100,
    risques: (e.risques_avec_voisinage as J[]).map((x) => ({
      term: String(x.term),
      avec: factorPct(x),
      sans: sans.get(String(x.term)) ?? Number.NaN,
    })),
  };
}
