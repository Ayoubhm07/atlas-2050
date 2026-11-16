/**
 * Types de l'API ATLAS 2050 (docs/api/openapi.json). Les réponses sont vérifiées à la
 * frontière par `guards.ts` avant d'être utilisées : on ne fait pas confiance au réseau.
 */

export interface Meta {
  total: number | null;
  page: number | null;
  limit: number | null;
  sources: string[];
}

export interface Envelope<T> {
  success: boolean;
  data: T | null;
  error: string | null;
  meta: Meta;
}

export type TypeLocal = "Maison" | "Appartement";
export type TypeFiltre = TypeLocal | "tous";
export type Dpe = "A" | "B" | "C" | "D" | "E" | "F" | "G";
export type DpeFiltre = Dpe | "tous";
export type AnneeFiltre = "2021" | "2022" | "2023" | "2024" | "tous";

export interface CommuneHit {
  code_insee: string;
  nom_commune: string;
  code_departement: string;
  lon: number;
  lat: number;
}

export interface HexCell {
  h3: string;
  n_ventes: number;
  prix_m2_median: number;
}

export interface StatsGroupe {
  type_local: string;
  annee: number;
  n_ventes: number;
  prix_m2_q1: number | null;
  prix_m2_median: number;
  prix_m2_q3: number | null;
  surface_mediane: number;
}

export interface CommuneStats {
  code_insee: string;
  groupes: StatsGroupe[];
}

export interface CommuneRisques {
  code_insee: string;
  nom_commune: string;
  n_catnat: number | null;
  n_catnat_10ans: number | null;
  date_reference: string | null;
  in_tri: boolean | null;
  ppri: boolean | null;
  n_ppr: number | null;
  azi: string | null;
  rga_iris: Record<string, number>;
}

export interface Fourchette {
  p10: number;
  p50: number;
  p90: number;
}

export interface Sensibilite {
  statut: string;
  risques: string[];
  avec_voisinage: Fourchette;
  sans_voisinage: Fourchette;
}

export type StatutScenario = "calcule" | "non_applicable" | "indisponible (DRIAS)" | "effet_non_estime";

export interface Scenario {
  id: string;
  libelle: string;
  statut: StatutScenario;
  message: string | null;
  prix_m2: Fourchette | null;
  valeur: Fourchette | null;
  location_interdite_depuis: number | null;
  composantes: string[];
  non_inclus: string[];
  sensibilite: Sensibilite | null;
}

export interface Facteur {
  variable: string;
  libelle: string;
  contribution_pct: number;
  valeur: number | null;
}

export interface Explication {
  base_prix_m2: number;
  autres_pct: number;
  prix_m2_modele: number;
}

export interface RisquesActuels {
  termes: string[];
  n_catnat_10ans: number | null;
  in_tri: boolean | null;
  ppri: boolean | null;
  azi: string | null;
  rga_exposition: string | null;
}

export interface Localisation {
  code_insee: string;
  nom_commune: string;
  code_iris: string;
  source: "coordonnees" | "adresse_ban";
  score_geocodage: number | null;
}

export interface Estimation {
  localisation: Localisation;
  date_valeur: string;
  type_local: TypeLocal;
  surface: number;
  prix_m2: Fourchette;
  valeur: Fourchette;
  risques_actuels: RisquesActuels;
  horizon: number;
  scenarios: Scenario[];
  facteurs: Facteur[];
  explication: Explication;
  avertissements: string[];
}

/** Bien décrit par l'utilisateur (le même pour les deux lieux d'une comparaison). */
export interface Bien {
  type_local: TypeLocal;
  surface: number;
  pieces: number;
  surface_terrain: number | null;
  dependances: number;
  dpe: Dpe | null;
}

/** Position : coordonnées (clic, commune) ou adresse (géocodée par l'API, en POST). */
export type Position =
  | { kind: "point"; lat: number; lon: number; label: string }
  | { kind: "adresse"; address: string };
