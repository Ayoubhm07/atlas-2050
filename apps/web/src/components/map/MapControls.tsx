"use client";

/**
 * Réglages de la carte, hydratés en différé : React.lazy dans un composant client est
 * rendu au serveur (HTML complet, lisible sans JavaScript, aucun décalage), puis son
 * chunk arrive après l'hydratation du reste ; la tâche d'hydratation est ainsi découpée.
 */
import { lazy, Suspense } from "react";
import type { Props } from "./MapControlsImpl";

const Impl = lazy(() => import("./MapControlsImpl"));

export function MapControls(props: Props) {
  return (
    <Suspense>
      <Impl {...props} />
    </Suspense>
  );
}
