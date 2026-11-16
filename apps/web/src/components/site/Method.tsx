import { eurosM2, nombre, pct, pctSigne } from "@/lib/format";
import { RISK_LABELS } from "@/lib/scenarios";
import type { MethodFigures } from "@/lib/server/method";

const NA = "non disponible";

/** Méthode : chiffres lus dans ml/results.json au rendu, jamais recopiés à la main. */
export function Method({ m }: { m: MethodFigures | null }) {
  return (
    <section id="methode" className="section" aria-labelledby="methode-titre">
      <div className="wrap">
        <p className="kicker">Méthode</p>
        <h2 id="methode-titre">Ce que le modèle sait, et ce qu&apos;il ne dit pas.</h2>
        {!m ? (
          <p className="alert">Chiffres du modèle indisponibles (ml/results.json illisible).</p>
        ) : (
          <>
            <p className="lede">
              Un LightGBM entraîné sur {nombre(m.nVentes)} ventes de logements de {nombre(m.nCommunes)} communes de Gironde ({m.annees[0]} à{" "}
              {m.annees[m.annees.length - 1]}), validé deux fois : sur l&apos;année suivante, et sur des communes qu&apos;il n&apos;a jamais
              vues. Run du {m.date}.
            </p>
            <p className="note">
              Trois effectifs, trois usages : le gold compte {nombre(m.nVentes + m.nExcluesTerrain)} ventes ; la carte en montre les
              hexagones d&apos;au moins 5 ventes ; le modèle apprend sur {nombre(m.nVentes)} d&apos;entre elles, sans les{" "}
              {nombre(m.nExcluesTerrain)} maisons de plus d&apos;un hectare de terrain (le prix y paie surtout le foncier).
            </p>
            <dl className="facts">
              <div><dt>Erreur moyenne, test 2024 ({nombre(m.nTest)} ventes)</dt><dd className="num">{eurosM2(Math.round(m.maeTemporel))}, soit {pct(m.mapeTemporel)}</dd></div>
              <div><dt>Erreur moyenne, communes jamais vues</dt><dd className="num">{eurosM2(Math.round(m.maeSpatial))}, soit {pct(m.mapeSpatial)}</dd></div>
              <div><dt>R², temporel et spatial</dt><dd className="num">{m.r2Temporel.toFixed(2).replace(".", ",")} et {m.r2Spatial.toFixed(2).replace(".", ",")}</dd></div>
              <div>
                <dt>Gain sur la régression Ridge, test 2024 (IC 95 %)</dt>
                <dd className="num">{eurosM2(Math.round(m.gainTemporel.diff))}, de {nombre(Math.round(m.gainTemporel.low))} à {nombre(Math.round(m.gainTemporel.high))}</dd>
              </div>
              <div><dt>Porte bloquante (gain significatif dans les deux validations)</dt><dd>{m.porte ? "passée" : "non passée"}</dd></div>
              <div><dt>Ventes avec un DPE rattaché</dt><dd className="num">{pct(m.partDpe)} ({nombre(m.nDpeApparies)})</dd></div>
            </dl>

            <h3>Les risques : deux bornes, aucune causale</h3>
            <p>
              Inondation, Cat-Nat et argiles sont mesurés à la commune ou à l&apos;IRIS. Avec le contrôle du prix du voisinage, une
              partie de l&apos;effet est absorbée ; sans lui, l&apos;effet se mêle à la localisation (bord de l&apos;eau, centre urbain).
              La vérité n&apos;est identifiable ni par l&apos;une ni par l&apos;autre : la fiche les publie comme sensibilité, non causale.
            </p>
            <div className="table-scroll">
              <table>
                <caption className="sr-only">Écart de prix associé à chaque risque, selon les deux bornes</caption>
                <thead>
                  <tr>
                    <th scope="col">Risque</th>
                    <th scope="col" className="r">Avec contrôle du voisinage</th>
                    <th scope="col" className="r">Sans contrôle</th>
                  </tr>
                </thead>
                <tbody>
                  {m.risques.map((r) => (
                    <tr key={r.term}>
                      <th scope="row">{RISK_LABELS[r.term] ?? r.term}</th>
                      <td className="r num">{Number.isFinite(r.avec) ? pctSigne(r.avec) : NA}</td>
                      <td className="r num">{Number.isFinite(r.sans) ? pctSigne(r.sans) : NA}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}

        <h3 style={{ marginTop: "2.5rem" }}>Ce qui reste en blanc</h3>
        <ul className="blanks">
          <li>
            <strong>Le climat.</strong> Les projections RCP 4.5 et 8.5 viennent de DRIAS, qui exige un compte et n&apos;a pas d&apos;API.
            Aucun fichier n&apos;est disponible : l&apos;API répond <span className="tag tag-drias">indisponible (DRIAS)</span> et aucun
            chiffre n&apos;est inventé, interpolé ou remplacé.
          </li>
          <li>
            <strong>La trajectoire.</strong> La projection compare la date de valeur et 2050, en euros constants, sans tendance de
            marché ni inflation. Elle ne dit pas à quel prix un bien se vendra.
          </li>
          <li>
            <strong>Les ventes individuelles.</strong> Aucune vente n&apos;est montrée : agrégats d&apos;au moins 5 ventes, ou estimation
            d&apos;un bien fictif (ADR 0005).
          </li>
          <li>
            <strong>Le bien lui-même.</strong> DVF ne décrit ni l&apos;état, ni l&apos;étage, ni la vue : une large part du prix
            n&apos;est pas observable, d&apos;où des fourchettes larges.
          </li>
          <li>
            <strong>Le reste de la France.</strong> Seule la Gironde est relevée ; 2021 ne couvre que le second semestre.
          </li>
        </ul>
        <p className="note">Méthode complète : docs/methodology.md et ml/report.md dans le dépôt.</p>
      </div>
    </section>
  );
}
