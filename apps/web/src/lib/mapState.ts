/** État de la carte partagé entre les réglages (colonne) et la vue (WebGL). */
import { createStore } from "./store";
import type { AnneeFiltre, DpeFiltre, TypeFiltre } from "./types";

export type Temps = AnneeFiltre | "2050";

export interface Filters {
  type: TypeFiltre;
  dpe: DpeFiltre;
  temps: Temps;
  sol: boolean;
}

export const DEFAULT_FILTERS: Filters = { type: "tous", dpe: "tous", temps: "tous", sol: true };

export const filtersStore = createStore<Filters>(DEFAULT_FILTERS);

export type MapStatus = "idle" | "loading" | "ready" | "error";
export const mapStatusStore = createStore<{ status: MapStatus; message: string | null }>({ status: "idle", message: null });

/** Le focus clavier doit passer sur la carte dès qu'elle est prête (bouton « Voir »). */
export const mapFocusRequest = createStore<boolean>(false);

/** Demande de chargement de la carte 3D (bouton, geste, réglage). */
export const mapIntentStore = createStore<number>(0);

export interface LegendState {
  breaks: number[];
  nCells: number;
  nVentes: number;
  res: 7 | 9;
  loading: boolean;
  error: string | null;
}

export const legendStore = createStore<LegendState | null>(null);

export interface Selection {
  lon: number;
  lat: number;
  hex: { h3: string; res: 7 | 9; prix: number; n: number; temps: Temps } | null;
}

export const selectionStore = createStore<Selection | null>(null);

/** Cellules affichées (pour le tableau accessible), mêmes données que la carte. */
export interface VisibleCell {
  h3: string;
  prix: number;
  n: number;
  lon: number;
  lat: number;
}

export const visibleCellsStore = createStore<VisibleCell[]>([]);

export const TEMPS_LABELS: Readonly<Record<Temps, string>> = {
  tous: "2021 à 2024",
  "2021": "2021 (2e sem.)",
  "2022": "2022",
  "2023": "2023",
  "2024": "2024",
  "2050": "2050",
};
