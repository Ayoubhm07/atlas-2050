"use client";

import { lazy, Suspense } from "react";
import { LazyMount } from "@/components/LazyMount";
import { pointRequest, useStore } from "@/lib/store";

const Estimator = lazy(() => import("./Estimator").then((m) => ({ default: m.Estimator })));

/** Le formulaire d'estimation n'est chargé qu'à l'approche de sa section, ou sur demande de la carte. */
export function EstimatorSlot() {
  const req = useStore(pointRequest);
  return (
    <LazyMount minHeight="40rem" anchor="estimer" when={req !== null}>
      <Suspense fallback={<p className="note" role="status">Chargement du formulaire…</p>}>
        <Estimator />
      </Suspense>
    </LazyMount>
  );
}
