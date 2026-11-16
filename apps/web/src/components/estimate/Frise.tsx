"use client";

/**
 * De la date de valeur à 2050 : deux états chiffrés (aujourd'hui, 2050) et, entre eux, le
 * seul calendrier connu (loi Climat et résilience). Aucune courbe n'est tracée entre les
 * deux dates : la projection compare deux états, elle ne calcule pas de trajectoire.
 */
import { dateLongue } from "@/lib/format";
import { LOI_CLIMAT } from "@/lib/scenarios";
import type { Dpe } from "@/lib/types";
import styles from "./estimate.module.css";

interface Props {
  dateValeur: string;
  horizon: number;
  dpe: Dpe | null;
  interditeDepuis: number | null;
}

export function Frise({ dateValeur, horizon, dpe, interditeDepuis }: Props) {
  const start = Number(dateValeur.slice(0, 4)) || 2025;
  const span = Math.max(1, horizon - start);
  const at = (y: number): string => `${((y - start) / span) * 100}%`;
  return (
    <figure className={styles.frise}>
      <figcaption className="sr-only">
        Frise de {start} à {horizon} : estimation à la date de valeur, interdictions de louer de la loi Climat et résilience, projection {horizon}.
      </figcaption>
      <div className={styles.friseTrack} aria-hidden="true">
        <span className={styles.friseGap} style={{ left: "2%", right: "2%" }}>
          aucune trajectoire calculée entre ces deux dates
        </span>
        <span className={`${styles.friseNode} ${styles.friseEnd}`} style={{ left: 0 }} />
        {LOI_CLIMAT.map((l) => (
          <span key={l.annee} className={styles.friseTick} data-active={dpe === l.classe ? "true" : "false"} style={{ left: at(l.annee) }} />
        ))}
        <span className={`${styles.friseNode} ${styles.friseEnd}`} style={{ left: "100%" }} />
      </div>
      <ol className={styles.friseList}>
        <li>
          <strong className="num">{dateLongue(dateValeur)}</strong> : date de valeur de l&apos;estimation (lendemain de la dernière vente
          relevée).
        </li>
        {LOI_CLIMAT.map((l) => (
          <li key={l.annee} data-active={dpe === l.classe ? "true" : "false"}>
            <strong className="num">{l.annee}</strong> : location interdite des logements classés {l.classe}
            {dpe === l.classe ? " (c'est la classe de ce bien)" : ""}.
          </li>
        ))}
        <li>
          <strong className="num">{horizon}</strong> : projection en fourchettes, en euros constants de la date de valeur.
        </li>
      </ol>
      <p className="note">
        Calendrier de la loi Climat et résilience, affiché mais pas converti en prix (docs/methodology.md).
        {interditeDepuis !== null && ` Pour ce bien, l'API indique une location interdite depuis ${interditeDepuis}.`}
      </p>
    </figure>
  );
}
