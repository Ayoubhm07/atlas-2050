import type { Poster } from "@/lib/server/poster";
import styles from "./hero.module.css";

/**
 * Le relevé : hexagones r7 réels de /hex, projetés côté serveur, 7 tracés (un par classe
 * de prix). SVG en ligne : il s'affiche dans la même peinture que le titre, sans requête,
 * lisible sans JavaScript. Le balayage d'arpentage est un voile CSS posé dessus.
 */
export function SurveyPoster({ poster }: { poster: Poster }) {
  return (
    <>
      <svg
        className={styles.poster}
        viewBox={`-20 -20 ${poster.width + 40} ${poster.height + 40}`}
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-labelledby="releve-titre releve-desc"
      >
        <title id="releve-titre">Relevé des prix de la Gironde par hexagone</title>
        <desc id="releve-desc">
          {`${poster.nCells} hexagones H3 de résolution 7, chacun d'au moins 5 ventes ; la couleur va du violet (prix au mètre carré les plus bas) à l'ivoire (les plus hauts). Un tableau des mêmes données est proposé dans la colonne de réglages.`}
        </desc>
        {poster.layers.map((l) => (
          <path key={l.color} fill={l.color} d={l.d} />
        ))}
      </svg>
      {/* voile d'arpentage : une ligne d'or balaie d'ouest en est et découvre le relevé */}
      <span className={styles.survey} aria-hidden="true" />
    </>
  );
}
