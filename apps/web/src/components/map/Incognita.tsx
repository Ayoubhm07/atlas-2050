"use client";

import { filtersStore } from "@/lib/mapState";
import styles from "./map.module.css";

/** 2050 : la carte se couvre de hachures. Aucune valeur par hexagone n'existe pour 2050. */
export function Incognita() {
  return (
    <>
      <div className={styles.incognita} aria-hidden="true" />
      <section className={styles.cartouche} aria-labelledby="incognita-titre">
        <p className="kicker">Terra incognita</p>
        <h3 id="incognita-titre">2050 n&apos;est pas sur la carte.</h3>
        <p className={styles.cartoucheLong}>
          Aucune vente n&apos;existe après 2024, et ATLAS ne projette pas la carte hexagone par hexagone. Les
          colonnes pâles sont les valeurs 2021 à 2024, gardées comme repère.
        </p>
        <p>
          La projection 2050 se fait bien par bien, en fourchette, en euros constants (sans tendance de marché). Le climat
          (scénarios RCP 4.5 et 8.5) reste <span className="tag tag-drias">indisponible (DRIAS)</span> : aucun chiffre
          n&apos;est publié.
        </p>
        <div className="cta" style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
          <a className="btn btn-primary" href="#estimer">
            Projeter un bien en 2050
          </a>
          <button type="button" className="btn btn-quiet" onClick={() => filtersStore.set((f) => ({ ...f, temps: "tous" }))}>
            Revenir aux ventes relevées
          </button>
        </div>
      </section>
    </>
  );
}
