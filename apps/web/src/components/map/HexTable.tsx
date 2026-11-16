"use client";

/**
 * Alternative accessible à la carte : les mêmes hexagones, en tableau. Le corps est
 * chargé seulement à l'ouverture (il a besoin de H3, partagé avec la carte).
 */
import { lazy, Suspense, useState } from "react";

const HexTableBody = lazy(() => import("./HexTableBody"));

export function HexTable() {
  const [open, setOpen] = useState(false);
  return (
    <details className="panel" onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}>
      <summary className="summary">Les mêmes données en tableau</summary>
      {open && (
        <Suspense fallback={<p className="note" role="status">Chargement du tableau…</p>}>
          <HexTableBody />
        </Suspense>
      )}
    </details>
  );
}
