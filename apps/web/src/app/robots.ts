import type { MetadataRoute } from "next";

/**
 * Les données brutes (API proxifiée, tuiles) ne sont jamais indexées (ADR 0005 ; l'API
 * renvoie aussi X-Robots-Tag: noindex). La page, faite d'agrégats d'au moins 5 ventes,
 * reste indexable : choix à confirmer par le founder avant toute mise en ligne.
 */
export default function robots(): MetadataRoute.Robots {
  return { rules: [{ userAgent: "*", allow: "/", disallow: ["/api/", "/tiles/"] }] };
}
