"use client";

import { useEffect, useState } from "react";
import styles from "./estimate.module.css";

/** Attente d'une estimation : ce qui se calcule, et le temps écoulé au-delà de 1,5 s. */
export function Pending({ slot, startedAt }: { slot: "A" | "B" | null; startedAt: number }) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const t = window.setInterval(() => setElapsed(performance.now() - startedAt), 250);
    return () => window.clearInterval(t);
  }, [startedAt]);
  return (
    <div className={`panel ${styles.pending}`} role="status">
      <div className={styles.pendingBar} aria-hidden="true" />
      <p>
        <strong>{slot ? `Lieu ${slot} : ` : ""}relevé en cours.</strong> Position, prix des ventes voisines antérieures, modèle,
        puis 20 000 tirages par scénario 2050.
      </p>
      {elapsed > 1500 && <p className="note num">{(elapsed / 1000).toFixed(1).replace(".", ",")} s</p>}
    </div>
  );
}
