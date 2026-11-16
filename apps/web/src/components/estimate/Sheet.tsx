"use client";

/** Fiche d'un bien : ce que l'API sait, dans l'ordre où on se pose les questions. */
import { CommunePanel } from "@/components/CommunePanel";
import { dateLongue, deNom, euros, eurosM2, fourchetteEuros, pctSigne } from "@/lib/format";
import { ecartMedianes, groupScenarios, RISK_LABELS, riskOf } from "@/lib/scenarios";
import type { Bien, Estimation } from "@/lib/types";
import { Frise } from "./Frise";
import { Gauge } from "./Gauge";
import { Waterfall } from "./Waterfall";
import styles from "./estimate.module.css";

interface Props {
  est: Estimation;
  bien: Bien;
  label: string;
  slot: "A" | "B" | null;
  domain?: [number, number];
}

function ouiNon(v: boolean | null): string {
  return v === null ? "inconnu" : v ? "oui" : "non";
}

export function Sheet({ est, bien, label, slot, domain }: Props) {
  const g = groupScenarios(est);
  const sq = g.statuQuo;
  const ecart = sq?.prix_m2 ? ecartMedianes(est.prix_m2, sq.prix_m2) : null;
  const titleId = `fiche-${slot ?? "seule"}`;
  const r = est.risques_actuels;
  const loc = est.localisation;
  return (
    <article className={`panel ${styles.sheet}`} aria-labelledby={titleId}>
      <header className={styles.sheetHead}>
        <p className="kicker">{slot ? `Lieu ${slot}` : "Fiche du bien"}</p>
        <h3 id={titleId}>
          {est.type_local} de {est.surface.toLocaleString("fr-FR")} m², {loc.nom_commune}
        </h3>
        <p className="note">
          {label}. IRIS {loc.code_iris}
          {loc.source === "adresse_ban" && loc.score_geocodage !== null
            ? `, adresse géocodée par la BAN (score ${loc.score_geocodage.toLocaleString("fr-FR", { maximumFractionDigits: 2 })})`
            : ""}
          . Date de valeur : {dateLongue(est.date_valeur)}.
        </p>
      </header>

      <div className={styles.headline}>
        <div>
          <p className={styles.bigLabel}>Valeur estimée, DPE au mix moyen des ventes (médiane)</p>
          <p className={`${styles.big} num`}>{euros(est.valeur.p50)}</p>
          <p className="note num">
            {fourchetteEuros(est.valeur.p10, est.valeur.p90)} (P10 à P90), soit {eurosM2(est.prix_m2.p50)}
          </p>
        </div>
        {sq?.valeur && (
          <div>
            <p className={styles.bigLabel}>
              En {est.horizon}, statu quo{bien.dpe ? `, classe ${bien.dpe}` : ""} (médiane)
            </p>
            <p className={`${styles.big} num`}>{euros(sq.valeur.p50)}</p>
            <p className="note num">
              {fourchetteEuros(sq.valeur.p10, sq.valeur.p90)}
              {bien.dpe && ecart !== null ? `, soit ${pctSigne(ecart)} : l'effet de la classe ${bien.dpe}` : ""}
            </p>
          </div>
        )}
      </div>
      <p className={styles.reading}>
        {bien.dpe
          ? `Le modèle de prix ignore le DPE : sa valeur vaut pour un bien au mix moyen des classes vendues. La projection 2050 lui applique l'écart de prix observé jusqu'en 2024 entre la classe ${bien.dpe} et ce mix, supposé persister. L'écart entre les deux montants est donc l'effet de la classe ${bien.dpe}, pas une évolution du marché : euros constants, sans tendance ni climat.`
          : "Sans étiquette DPE, le bien reste au mix moyen des classes : aucun effet DPE n'est appliqué, et 2050 ne diffère d'aujourd'hui que par le tirage des erreurs du modèle."}
      </p>

      <h4>La fourchette, pas le chiffre</h4>
      <Gauge est={est} domain={domain} />

      {g.sensibilites.length > 0 && (
        <p className="note">
          Sensibilité, non causal : ces lignes disent ce que vaudrait le bien si un risque absent aujourd&apos;hui apparaissait dans la
          commune. Deux bornes, aucune n&apos;est un effet causal : avec contrôle du voisinage (effet en partie absorbé), sans (effet
          confondu par la localisation, signe parfois faux). La fourchette publiée couvre les deux.
        </p>
      )}
      {g.dejaPresents.length > 0 && (
        <p className="note">
          Déjà présents, donc déjà dans le prix estimé et non simulés : {g.dejaPresents.map((s) => RISK_LABELS[riskOf(s)] ?? s.libelle).join(" ; ")}.
        </p>
      )}

      <h4>De la date de valeur à {est.horizon}</h4>
      <Frise dateValeur={est.date_valeur} horizon={est.horizon} dpe={bien.dpe} interditeDepuis={sq?.location_interdite_depuis ?? null} />

      <h4>Pourquoi ce prix</h4>
      <Waterfall est={est} />

      <h4>Risques actuels de la commune</h4>
      <dl className="facts">
        <div><dt>PPRI (inondation)</dt><dd>{ouiNon(r.ppri)}</dd></div>
        <div><dt>Territoire à risque d&apos;inondation (TRI)</dt><dd>{ouiNon(r.in_tri)}</dd></div>
        <div><dt>Arrêtés Cat-Nat, 10 ans</dt><dd className="num">{r.n_catnat_10ans ?? "inconnu"}</dd></div>
        <div><dt>Argiles (IRIS)</dt><dd>{r.rga_exposition ?? "inconnu"}</dd></div>
        <div><dt>Atlas des zones inondables</dt><dd>{r.azi ?? "inconnu"}</dd></div>
      </dl>
      <p className="note">Mesurés à la commune (argiles : à l&apos;IRIS). Ils ne disent pas si ce bien précis est exposé.</p>

      {sq && (
        <>
          <h4>Ce que la projection compte, et ce qu&apos;elle laisse en blanc</h4>
          <div className={styles.inout}>
            <div>
              <p className={styles.bigLabel}>Inclus</p>
              <ul>{sq.composantes.map((c) => <li key={c}>{c}</li>)}</ul>
            </div>
            <div className="hatched">
              <p className={styles.bigLabel}>Non inclus</p>
              <ul>{sq.non_inclus.map((c) => <li key={c}>{c}</li>)}</ul>
            </div>
          </div>
        </>
      )}

      <details className={styles.warn}>
        <summary className="summary">Ce que dit l&apos;API sur cette estimation ({est.avertissements.length} avertissements)</summary>
        <ul>{est.avertissements.map((a) => <li key={a}>{a}</li>)}</ul>
      </details>

      <details className={styles.warn}>
        <summary className="summary">Les ventes et les risques {deNom(loc.nom_commune)}</summary>
        <CommunePanel commune={{ code_insee: loc.code_insee, nom_commune: loc.nom_commune }} heading="h4" />
      </details>
    </article>
  );
}
