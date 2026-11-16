/**
 * Petit magasin partagé entre la carte et la fiche (sans fournisseur React, pour ne pas
 * alourdir l'hydratation). Immuable : chaque mise à jour remplace l'état.
 */
import { useSyncExternalStore } from "react";

type Listener = () => void;

export interface Store<T> {
  get: () => T;
  set: (next: T | ((prev: T) => T)) => void;
  subscribe: (l: Listener) => () => void;
}

export function createStore<T>(initial: T): Store<T> {
  let state = initial;
  const listeners = new Set<Listener>();
  return {
    get: () => state,
    set: (next) => {
      state = typeof next === "function" ? (next as (p: T) => T)(state) : next;
      listeners.forEach((l) => l());
    },
    subscribe: (l) => {
      listeners.add(l);
      return () => {
        listeners.delete(l);
      };
    },
  };
}

export function useStore<T>(store: Store<T>): T {
  return useSyncExternalStore(store.subscribe, store.get, store.get);
}

/** Point choisi sur la carte pour une estimation (lieu A ou B), avec un jeton de requête. */
export interface PointRequest {
  slot: "A" | "B";
  lat: number;
  lon: number;
  label: string;
  nonce: number;
}

export const pointRequest = createStore<PointRequest | null>(null);

/** Demande de cadrage de la carte (recherche de commune, tableau). */
export interface FlyRequest {
  lon: number;
  lat: number;
  zoom: number;
  nonce: number;
}

export const flyRequest = createStore<FlyRequest | null>(null);

let counter = 0;

/** Jeton croissant : deux demandes identiques successives restent distinctes. */
export function nextNonce(): number {
  counter += 1;
  return counter;
}
