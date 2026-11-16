import styles from "./site.module.css";

export function SiteHeader() {
  return (
    <header className={styles.header}>
      <a className={styles.mark} href="#haut" aria-label="ATLAS 2050, haut de page">
        <svg width="22" height="24" viewBox="0 0 22 24" aria-hidden="true">
          <path d="M11 1 21 6.5v11L11 23 1 17.5v-11Z" fill="none" stroke="currentColor" strokeWidth="1.6" />
          <path d="M11 7v10M6.5 9.5v7M15.5 11v6" stroke="#fbe7a1" strokeWidth="1.8" strokeLinecap="round" />
        </svg>
        <span>ATLAS 2050</span>
      </a>
      <nav aria-label="Sections">
        <ul className={styles.nav}>
          <li><a href="#carte">Carte</a></li>
          <li><a href="#estimer">Estimer</a></li>
          <li><a href="#methode">Méthode</a></li>
        </ul>
      </nav>
    </header>
  );
}
