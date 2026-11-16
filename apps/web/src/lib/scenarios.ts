/**
 * Lecture des scénarios et du waterfall SHAP renvoyés par /estimate. Fonctions pures :
 * rien n'est inventé, tout chiffre affiché est un champ de l'API ou un rapport entre
 * deux champs de l'API (écart des médianes), étiqueté comme tel.
 */
import type { Estimation, Explication, Facteur, Fourchette, Scenario } from "./types";

export const RISK_LABELS: Readonly<Record<string, string>> = {
  ppri: "Plan de prévention du risque inondation (PPRI) dans la commune",
  in_tri: "Commune en territoire à risque important d'inondation (TRI)",
  catnat_3plus: "3 arrêtés Cat-Nat ou plus en 10 ans dans la commune",
  rga_forte: "Exposition forte au retrait-gonflement des argiles (IRIS)",
};

export const LOI_CLIMAT: readonly { annee: number; classe: string }[] = [
  { annee: 2025, classe: "G" },
  { annee: 2028, classe: "F" },
  { annee: 2034, classe: "E" },
];

/** Écart relatif des médianes P50 (futur / actuel − 1), en %. */
export function ecartMedianes(actuel: Fourchette, futur: Fourchette): number {
  if (actuel.p50 <= 0) return 0;
  return (futur.p50 / actuel.p50 - 1) * 100;
}

export interface ScenarioGroups {
  statuQuo: Scenario | undefined;
  renovation: Scenario | undefined;
  sensibilites: Scenario[];
  dejaPresents: Scenario[];
  nonEstimes: Scenario[];
  climat: Scenario[];
}

export function groupScenarios(est: Estimation): ScenarioGroups {
  const risk = est.scenarios.filter((s) => s.id.startsWith("nouveau_risque_"));
  return {
    statuQuo: est.scenarios.find((s) => s.id === "statu_quo"),
    renovation: est.scenarios.find((s) => s.id === "renovation_D"),
    sensibilites: risk.filter((s) => s.statut === "calcule"),
    dejaPresents: risk.filter((s) => s.statut === "non_applicable"),
    nonEstimes: risk.filter((s) => s.statut === "effet_non_estime"),
    climat: est.scenarios.filter((s) => s.id.startsWith("climat_")),
  };
}

export function riskOf(s: Scenario): string {
  return s.id.replace("nouveau_risque_", "");
}

export type StepKind = "base" | "hausse" | "baisse" | "total";

export interface WaterfallStep {
  key: string;
  label: string;
  kind: StepKind;
  /** prix/m² avant et après l'étape (base et total : from = 0). */
  from: number;
  to: number;
  pct: number | null;
  valeur: number | null;
  variable: string | null;
}

/**
 * Waterfall multiplicatif : base × Π(1 + c_i) × (1 + autres) = prédiction du modèle.
 * La dernière barre est la prédiction renvoyée par l'API (pas le produit recalculé),
 * l'écart d'arrondi éventuel est rendu dans `ecartArrondi`.
 */
export function waterfall(
  expl: Explication,
  facteurs: readonly Facteur[],
): { steps: WaterfallStep[]; ecartArrondi: number } {
  const steps: WaterfallStep[] = [
    { key: "base", label: "Point de départ du modèle (tous biens de Gironde)", kind: "base", from: 0, to: expl.base_prix_m2, pct: null, valeur: null, variable: null },
  ];
  let level = expl.base_prix_m2;
  const push = (key: string, label: string, pct: number, valeur: number | null, variable: string | null): void => {
    const next = level * (1 + pct / 100);
    steps.push({ key, label, kind: pct >= 0 ? "hausse" : "baisse", from: level, to: next, pct, valeur, variable });
    level = next;
  };
  const cap = (t: string): string => t.charAt(0).toUpperCase() + t.slice(1);
  facteurs.forEach((f) => push(f.variable, cap(f.libelle), f.contribution_pct, f.valeur, f.variable));
  push("autres", "Toutes les autres variables du modèle", expl.autres_pct, null, null);
  steps.push({ key: "total", label: "Prédiction du modèle", kind: "total", from: 0, to: expl.prix_m2_modele, pct: null, valeur: null, variable: null });
  return { steps, ecartArrondi: expl.prix_m2_modele - level };
}

/** Domaine commun [min, max] d'une liste de fourchettes, avec une marge de 4 %. */
export function domaine(fs: readonly Fourchette[]): [number, number] {
  if (fs.length === 0) return [0, 1];
  const lo = Math.min(...fs.map((f) => f.p10));
  const hi = Math.max(...fs.map((f) => f.p90));
  const pad = (hi - lo) * 0.04 || hi * 0.04 || 1;
  return [Math.max(0, lo - pad), hi + pad];
}

/** Valeur affichable d'un facteur (unités connues ; voisinage et position : jamais). */
export function valeurFacteur(f: Facteur): string | null {
  if (f.valeur === null) return null;
  const n = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 3 });
  switch (f.variable) {
    case "log_surface":
    case "log_terrain":
      return `${n.format(f.valeur)} m²`;
    case "revenu_median":
      return `${new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 }).format(f.valeur)} € par an`;
    case "est_maison":
      return f.valeur === 1 ? "maison" : "appartement";
    default:
      return n.format(f.valeur);
  }
}
