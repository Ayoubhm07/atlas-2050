"use client";

import { useEffect, useState } from "react";
import { errorMessage } from "@/lib/api";
import { coordonnees, eurosM2, nombre } from "@/lib/format";
import { loadR7 } from "@/lib/hexdata";
import { filtersStore, mapFocusRequest, mapIntentStore, mapStatusStore, TEMPS_LABELS, visibleCellsStore, type VisibleCell } from "@/lib/mapState";
import { flyRequest, nextNonce, useStore } from "@/lib/store";
import { requestEstimate } from "./SelectionCard";

const PAGE = 12;

export default function HexTableBody() {
  const f = useStore(filtersStore);
  const status = useStore(mapStatusStore).status;
  const visible = useStore(visibleCellsStore);
  const [all, setAll] = useState<VisibleCell[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [n, setN] = useState(PAGE);
  const mapReady = status === "ready";

  useEffect(() => {
    if (mapReady) return;
    const ctrl = new AbortController();
    loadR7(f.type, f.dpe, ctrl.signal)
      .then((data) => {
        const key = f.temps === "2050" ? "tous" : f.temps;
        setAll(
          data
            .flatMap((d) => {
              const v = d.vals[key];
              return v ? [{ h3: d.h3, prix: v.p, n: v.n, lon: d.lon, lat: d.lat }] : [];
            })
            .sort((a, b) => b.prix - a.prix),
        );
        setError(null);
      })
      .catch((err: unknown) => !ctrl.signal.aborted && setError(errorMessage(err)));
    return () => ctrl.abort();
  }, [mapReady, f.type, f.dpe, f.temps]);

  const rows = mapReady ? visible : (all ?? []);
  const scope = mapReady ? "dans la vue actuelle de la carte" : "de toute la Gironde (résolution 7)";

  const voir = (c: VisibleCell): void => {
    flyRequest.set({ lon: c.lon, lat: c.lat, zoom: 11.5, nonce: nextNonce() });
    const canvas = document.querySelector<HTMLCanvasElement>("canvas.maplibregl-canvas");
    if (mapStatusStore.get().status === "ready" && canvas) {
      canvas.focus({ preventScroll: true });
      canvas.closest("[role=region]")?.scrollIntoView({ block: "nearest" });
    } else {
      mapFocusRequest.set(true);
      if (mapStatusStore.get().status === "idle") mapIntentStore.set((k) => k + 1);
    }
  };

  if (error) return <p className="alert" role="alert">{error}</p>;
  if (!mapReady && all === null) return <p className="note" role="status">Lecture des hexagones…</p>;
  return (
    <div>
      <p className="note">
        {nombre(rows.length)} hexagones {scope}, {TEMPS_LABELS[f.temps === "2050" ? "tous" : f.temps]}, du plus cher au moins cher.
        {f.temps === "2050" && " Pas de valeur 2050 par hexagone : repère 2021 à 2024."}
      </p>
      <div className="table-scroll">
        <table>
          <caption className="sr-only">Hexagones H3 : prix médian au mètre carré et nombre de ventes</caption>
          <thead>
            <tr>
              <th scope="col">Rang</th>
              <th scope="col" className="r">Prix médian</th>
              <th scope="col" className="r">Ventes</th>
              <th scope="col">Centre</th>
              <th scope="col"><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, n).map((c, i) => (
              <tr key={c.h3}>
                <td className="num">{i + 1}</td>
                <td className="r num">{eurosM2(c.prix)}</td>
                <td className="r num">{nombre(c.n)}</td>
                <td className="num">{coordonnees(c.lat, c.lon)}</td>
                <td>
                  <div style={{ display: "flex", gap: "0.3rem", flexWrap: "wrap" }}>
                    <button type="button" className="btn btn-quiet" onClick={() => voir(c)} aria-label={`Voir l'hexagone ${i + 1} sur la carte`}>
                      Voir
                    </button>
                    <button
                      type="button"
                      className="btn btn-quiet"
                      onClick={() => requestEstimate("A", c.lat, c.lon, `Centre de l'hexagone ${coordonnees(c.lat, c.lon)}`)}
                      aria-label={`Estimer ici, au centre de l'hexagone ${i + 1}`}
                    >
                      Estimer ici
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > n && (
        <button type="button" className="btn" onClick={() => setN((k) => k + PAGE)} style={{ marginTop: "0.75rem" }}>
          Afficher {Math.min(PAGE, rows.length - n)} de plus
        </button>
      )}
    </div>
  );
}
