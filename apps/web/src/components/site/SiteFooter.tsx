import styles from "./site.module.css";

/** Sources, licences et crédits : vérifiés dans docs/sources.md et les métadonnées des producteurs. */
export function SiteFooter() {
  return (
    <footer className={styles.footer}>
      <div className="wrap">
        <h2>Sources, licences, crédits</h2>
        <ul className={styles.credits}>
          <li>Ventes : DVF géolocalisées, DGFiP et Etalab, Licence Ouverte 2.0</li>
          <li>Risques : Géorisques (GASPAR, RGA), licence Etalab 2.0</li>
          <li>Revenus : INSEE Filosofi 2021 par IRIS</li>
          <li>Contours des communes et IRIS : IGN et INSEE, Contours IRIS, Licence Ouverte</li>
          <li>DPE : ADEME, Licence Ouverte 2.0</li>
          <li>Géocodage des adresses (côté API) : Base Adresse Nationale, Licence Ouverte 2.0</li>
          <li>Carte : MapLibre GL JS (BSD-3), deck.gl (MIT), H3 (Apache 2.0), tuiles servies par Martin (MIT ou Apache 2.0)</li>
          <li>Polices : Fraunces et Instrument Sans (SIL Open Font License), hébergées avec le site</li>
        </ul>
        <p>
          Aucun fond de carte tiers : le sol est dessiné avec nos propres contours. Aucun cookie, aucune mesure d&apos;audience. Les
          données de l&apos;API ne sont pas indexables (en-tête noindex, ADR 0005).
        </p>
      </div>
    </footer>
  );
}
