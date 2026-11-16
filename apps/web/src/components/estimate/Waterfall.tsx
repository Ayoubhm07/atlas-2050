"use client";

/**
 * Pourquoi ce prix : waterfall SHAP (TreeSHAP natif de LightGBM, additif en log-prix,
 * présenté en effets multiplicatifs). Il part de la référence du modèle et se referme sur
 * sa prédiction ponctuelle, grâce au champ `explication` de l'API.
 */
import { eurosM2, pctSigne } from "@/lib/format";
import { valeurFacteur, waterfall } from "@/lib/scenarios";
import type { Estimation } from "@/lib/types";
import styles from "./estimate.module.css";

export function Waterfall({ est }: { est: Estimation }) {
  const { steps, ecartArrondi } = waterfall(est.explication, est.facteurs);
  const hi = Math.max(...steps.map((s) => Math.max(s.from, s.to))) * 1.04;
  const x = (v: number): string => `${(v / hi) * 100}%`;
  return (
    <figure className={styles.waterfall}>
      <figcaption className="sr-only">
        Décomposition du prix au mètre carré prédit par le modèle : point de départ, effet de chaque variable, prédiction.
      </figcaption>
      <ol className={styles.wfRows}>
        {steps.map((s, i) => {
          const lo = Math.min(s.from, s.to);
          const w = Math.abs(s.to - s.from);
          const val = s.variable ? valeurFacteur({ variable: s.variable, libelle: s.label, contribution_pct: s.pct ?? 0, valeur: s.valeur }) : null;
          return (
            <li key={s.key} className={styles.wfRow} data-kind={s.kind}>
              <span className={styles.wfLabel}>
                {s.label}
                {val && <span className="note"> ({val})</span>}
              </span>
              <span className={styles.wfTrack} aria-hidden="true">
                <span className={styles.wfBar} style={{ left: x(lo), width: `max(2px, ${x(w)})`, animationDelay: `${i * 90}ms` }} />
              </span>
              <span className={`${styles.wfValue} num`}>{s.pct === null ? eurosM2(s.to) : pctSigne(s.pct)}</span>
            </li>
          );
        })}
      </ol>
      <p className="note">
        Les six variables qui pèsent le plus pour ce bien, puis toutes les autres réunies. Le voisinage et la position sont donnés en
        effet, jamais en valeur (ADR 0005). La fourchette ajoute à cette prédiction l&apos;erreur observée du modèle : médiane{" "}
        {eurosM2(est.prix_m2.p50)}.
        {Math.abs(ecartArrondi) >= 10 && ` Écart d'arrondi des pourcentages : ${eurosM2(Math.round(ecartArrondi))}.`}
      </p>
    </figure>
  );
}
