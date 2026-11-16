/**
 * Vérification des réponses de l'API à la frontière. Légère (pas de bibliothèque de
 * schémas dans le JS initial) mais stricte sur ce que l'interface lit réellement :
 * une réponse inattendue devient une erreur lisible, jamais un chiffre faux affiché.
 */
import type {
  CommuneHit,
  CommuneRisques,
  CommuneStats,
  Estimation,
  Fourchette,
  HexCell,
  Scenario,
} from "./types";

export class ShapeError extends Error {
  constructor(what: string) {
    super(`Réponse de l'API inattendue (${what})`);
    this.name = "ShapeError";
  }
}

type Rec = Record<string, unknown>;

const isRec = (v: unknown): v is Rec => typeof v === "object" && v !== null && !Array.isArray(v);
const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const isStr = (v: unknown): v is string => typeof v === "string";
const isNumOrNull = (v: unknown): boolean => v === null || isNum(v);
const isBoolOrNull = (v: unknown): boolean => v === null || typeof v === "boolean";
const isStrOrNull = (v: unknown): boolean => v === null || isStr(v);

function need(ok: boolean, what: string): void {
  if (!ok) throw new ShapeError(what);
}

export function asHexCells(v: unknown): HexCell[] {
  need(Array.isArray(v), "hexagones");
  return (v as unknown[]).map((c) => {
    need(isRec(c) && isStr(c.h3) && isNum(c.n_ventes) && isNum(c.prix_m2_median), "hexagone");
    const r = c as Rec;
    // ADR 0005 : un agrégat de moins de 5 ventes ne doit jamais être affiché
    need((r.n_ventes as number) >= 5, "hexagone sous le seuil de 5 ventes");
    return { h3: r.h3 as string, n_ventes: r.n_ventes as number, prix_m2_median: r.prix_m2_median as number };
  });
}

export function asCommuneHits(v: unknown): CommuneHit[] {
  need(Array.isArray(v), "communes");
  return (v as unknown[]).map((c) => {
    need(
      isRec(c) && isStr(c.code_insee) && isStr(c.nom_commune) && isNum(c.lon) && isNum(c.lat),
      "commune",
    );
    const r = c as Rec;
    return {
      code_insee: r.code_insee as string,
      nom_commune: r.nom_commune as string,
      code_departement: isStr(r.code_departement) ? r.code_departement : "",
      lon: r.lon as number,
      lat: r.lat as number,
    };
  });
}

export function asCommuneStats(v: unknown): CommuneStats {
  need(isRec(v) && isStr(v.code_insee) && Array.isArray(v.groupes), "statistiques");
  const r = v as Rec;
  for (const g of r.groupes as unknown[]) {
    need(
      isRec(g) &&
        isStr(g.type_local) &&
        isNum(g.annee) &&
        isNum(g.n_ventes) &&
        (g.n_ventes as number) >= 5 &&
        isNum(g.prix_m2_median) &&
        isNumOrNull(g.prix_m2_q1) &&
        isNumOrNull(g.prix_m2_q3) &&
        isNum(g.surface_mediane),
      "groupe de ventes",
    );
  }
  return v as unknown as CommuneStats;
}

export function asCommuneRisques(v: unknown): CommuneRisques {
  need(
    isRec(v) &&
      isStr(v.code_insee) &&
      isStr(v.nom_commune) &&
      isNumOrNull(v.n_catnat_10ans) &&
      isBoolOrNull(v.in_tri) &&
      isBoolOrNull(v.ppri) &&
      isStrOrNull(v.azi) &&
      isRec(v.rga_iris ?? {}),
    "risques",
  );
  const r = v as Rec;
  return { ...(r as unknown as CommuneRisques), rga_iris: (r.rga_iris as Record<string, number> | null) ?? {} };
}

function isFourchette(v: unknown): v is Fourchette {
  return isRec(v) && isNum(v.p10) && isNum(v.p50) && isNum(v.p90) && v.p10 <= v.p50 && v.p50 <= v.p90;
}

const STATUTS = new Set(["calcule", "non_applicable", "indisponible (DRIAS)", "effet_non_estime"]);

function checkScenario(s: unknown): void {
  need(isRec(s) && isStr(s.id) && isStr(s.libelle) && STATUTS.has(String(s.statut)), "scénario");
  const r = s as Rec;
  if (r.statut === "calcule") {
    need(isFourchette(r.prix_m2) && isFourchette(r.valeur), "fourchette de scénario");
  } else {
    // Un scénario non calculé ne doit porter aucun chiffre (DRIAS : jamais chiffré)
    need(r.prix_m2 === null && r.valeur === null, "scénario non calculé avec un chiffre");
  }
  if (r.sensibilite !== null && r.sensibilite !== undefined) {
    const sens = r.sensibilite as Rec;
    need(isFourchette(sens.avec_voisinage) && isFourchette(sens.sans_voisinage), "sensibilité");
  }
}

export function asEstimation(v: unknown): Estimation {
  need(isRec(v), "estimation");
  const r = v as Rec;
  need(isFourchette(r.prix_m2) && isFourchette(r.valeur), "fourchette actuelle");
  need(isStr(r.date_valeur) && isNum(r.horizon) && isNum(r.surface), "date ou horizon");
  need(isRec(r.localisation) && isStr((r.localisation as Rec).nom_commune), "localisation");
  need(isRec(r.risques_actuels) && Array.isArray((r.risques_actuels as Rec).termes), "risques actuels");
  need(Array.isArray(r.scenarios) && Array.isArray(r.facteurs) && Array.isArray(r.avertissements), "listes");
  (r.scenarios as unknown[]).forEach(checkScenario);
  for (const f of r.facteurs as unknown[]) {
    need(isRec(f) && isStr(f.variable) && isStr(f.libelle) && isNum(f.contribution_pct), "facteur");
  }
  const e = r.explication;
  need(isRec(e) && isNum(e.base_prix_m2) && isNum(e.autres_pct) && isNum(e.prix_m2_modele), "explication");
  return v as unknown as Estimation;
}

export function scenarioById(est: Estimation, id: string): Scenario | undefined {
  return est.scenarios.find((s) => s.id === id);
}
