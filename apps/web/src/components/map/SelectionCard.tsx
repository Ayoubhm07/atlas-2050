"use client";

import { coordonnees, eurosM2, nombre } from "@/lib/format";
import { selectionStore, TEMPS_LABELS } from "@/lib/mapState";
import { nextNonce, pointRequest, useStore } from "@/lib/store";
import styles from "./map.module.css";

export function requestEstimate(slot: "A" | "B", lat: number, lon: number, label: string): void {
  pointRequest.set({ slot, lat, lon, label, nonce: nextNonce() });
  document.getElementById("estimer")?.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  // le focus suit le lecteur : titre de la section d'estimation
  document.getElementById("estimer-titre")?.focus({ preventScroll: true });
}

/** Ce qu'on a touché sur la carte : l'hexagone (agrégat ≥ 5 ventes) et le point. */
export function SelectionCard() {
  const sel = useStore(selectionStore);
  if (!sel) return null;
  const where = coordonnees(sel.lat, sel.lon);
  return (
    <section className={styles.selection} aria-label="Point choisi sur la carte" aria-live="polite">
      <button type="button" className={styles.close} aria-label="Fermer" onClick={() => selectionStore.set(null)}>
        ×
      </button>
      {sel.hex ? (
        <>
          <strong>
            Hexagone H3 r{sel.hex.res}, {TEMPS_LABELS[sel.hex.temps === "2050" ? "tous" : sel.hex.temps]}
          </strong>
          <dl>
            <dt>Prix médian</dt>
            <dd className="num">{eurosM2(sel.hex.prix)}</dd>
            <dt>Ventes</dt>
            <dd className="num">{nombre(sel.hex.n)}</dd>
            <dt>Point</dt>
            <dd className="num">{where}</dd>
          </dl>
        </>
      ) : (
        <p style={{ margin: "0 2.5rem 0.75rem 0" }}>
          Aucun hexagone publié ici (moins de 5 ventes ou hors filtre). Point : <span className="num">{where}</span>
        </p>
      )}
      <div className={styles.selRow}>
        <button type="button" className="btn btn-primary" onClick={() => requestEstimate("A", sel.lat, sel.lon, `Point ${where}`)}>
          Estimer un bien ici
        </button>
        <button type="button" className="btn" onClick={() => requestEstimate("B", sel.lat, sel.lon, `Point ${where}`)}>
          Comparer avec ce lieu
        </button>
      </div>
    </section>
  );
}
