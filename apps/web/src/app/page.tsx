import { Suspense } from "react";
import { SurveyPoster } from "@/components/hero/SurveyPoster";
import heroStyles from "@/components/hero/hero.module.css";
import { EstimatorSlot } from "@/components/estimate/EstimatorSlot";
import { HexTable } from "@/components/map/HexTable";
import { MapControls } from "@/components/map/MapControls";
import { MapViewport } from "@/components/map/MapViewport";
import { Method } from "@/components/site/Method";
import { SiteFooter } from "@/components/site/SiteFooter";
import { SiteHeader } from "@/components/site/SiteHeader";
import { nombre } from "@/lib/format";
import { loadGirondeHex } from "@/lib/server/data";
import { loadMethodFigures, type MethodFigures } from "@/lib/server/method";
import { buildPoster } from "@/lib/server/poster";

// Rendu à la demande : l'affiche est faite des vraies données de l'API locale (cache 10 min).
export const dynamic = "force-dynamic";

function safeMethod(): MethodFigures | null {
  try {
    return loadMethodFigures();
  } catch {
    return null;
  }
}

export default async function Home() {
  const hex = await loadGirondeHex();
  const poster = hex.ok ? buildPoster(hex.data) : null;
  const method = safeMethod();

  return (
    <>
      <a className="skip" href="#contenu">
        Aller au contenu
      </a>
      <SiteHeader />
      <main id="contenu">
        <section id="haut" className={heroStyles.stage} aria-labelledby="titre">
          <div className={heroStyles.side}>
            <div>
              <p className="kicker">Gironde, ventes 2021 à 2024, projection 2050</p>
              <h1 id="titre" className={heroStyles.title}>
                Ce que la Gironde vaut, <em>et ce qu&apos;on ne sait pas encore.</em>
              </h1>
            </div>
            {poster ? (
              <p className="lede">
                {nombre(poster.nVentes)} ventes de logements relevées, agrégées en {nombre(poster.nCells)} hexagones d&apos;au moins 5
                ventes. Ce qui n&apos;est pas mesuré reste en blanc : le climat de 2050 n&apos;est pas chiffré, faute de données DRIAS.
              </p>
            ) : (
              <p className="alert" role="alert">
                {hex.ok ? "Aucun hexagone renvoyé par l'API." : hex.error}
              </p>
            )}
            <div className={heroStyles.cta}>
              <a className="btn btn-primary" href="#estimer">
                Estimer un bien
              </a>
              <a className="btn" href="#methode">
                Lire la méthode
              </a>
            </div>
            <div id="carte">
              <h2 className="sr-only">Carte et réglages</h2>
              {/* chaque îlot client derrière son Suspense : hydratation découpée, moins de tâches longues */}
              <Suspense>
                <MapControls
                  initial={poster ? { breaks: poster.breaks, nCells: poster.nCells, nVentes: poster.nVentes } : null}
                  partDpe={method?.partDpe ?? Number.NaN}
                />
              </Suspense>
            </div>
            <Suspense>
              <HexTable />
            </Suspense>
          </div>
          {/* pas de Suspense ici : React sortirait l'affiche (environ 45 kB) du flux initial et
              elle ne s'afficherait plus sans JavaScript */}
          <MapViewport
            poster={
              poster ? (
                <SurveyPoster poster={poster} />
              ) : (
                <p className={heroStyles.apiDown}>L&apos;affiche du relevé attend l&apos;API locale.</p>
              )
            }
          />
        </section>

        <section id="estimer" className="section" aria-labelledby="estimer-titre">
          <div className="wrap">
            <p className="kicker">Fiche d&apos;un bien</p>
            <h2 id="estimer-titre" tabIndex={-1}>La fourchette, pas le chiffre.</h2>
            <p className="lede">
              Un bien fictif, un lieu, la réponse du modèle : sa valeur à la date de valeur, sa projection 2050 en euros constants,
              les sensibilités aux risques (non causales), et ce qui reste inconnu.
            </p>
            <noscript>
              <p className="alert">L&apos;estimation interroge l&apos;API locale et demande JavaScript. La méthode, plus bas, se lit sans.</p>
            </noscript>
            <EstimatorSlot />
          </div>
        </section>

        <Method m={method} />
      </main>
      <SiteFooter />
    </>
  );
}
