"use client";

/**
 * Fiche d'une commune : prix par type et par année (groupes ≥ 5 ventes, quartiles ≥ 11)
 * et risques actuels (Géorisques). Tableau : c'est aussi l'alternative lisible à la carte.
 */
import { useEffect, useState } from "react";
import { errorMessage, fetchCommuneRisques, fetchCommuneStats } from "@/lib/api";
import { deNom, eurosM2, nombre } from "@/lib/format";
import type { CommuneHit, CommuneRisques, CommuneStats } from "@/lib/types";

type State =
  | { kind: "loading"; code?: string }
  | { kind: "error"; message: string; code?: string }
  | { kind: "ok"; code?: string; stats: CommuneStats | null; risques: CommuneRisques | null; statsError: string | null };

function ouiNon(v: boolean | null): string {
  return v === null ? "inconnu" : v ? "oui" : "non";
}

export function CommunePanel({ commune, heading = "h3" }: { commune: Pick<CommuneHit, "code_insee" | "nom_commune">; heading?: "h3" | "h4" }) {
  const H = heading;
  const [loaded, setState] = useState<State>({ kind: "loading" });
  // Résultat d'une autre commune : on est de nouveau en chargement (aucun setState synchrone).
  const state: State = loaded.code === commune.code_insee ? loaded : { kind: "loading" };

  useEffect(() => {
    const ctrl = new AbortController();
    Promise.allSettled([
      fetchCommuneStats(commune.code_insee, { signal: ctrl.signal }),
      fetchCommuneRisques(commune.code_insee, { signal: ctrl.signal }),
    ]).then(([s, r]) => {
      if (ctrl.signal.aborted) return;
      if (s.status === "rejected" && r.status === "rejected") {
        setState({ kind: "error", message: errorMessage(r.reason), code: commune.code_insee });
        return;
      }
      setState({
        kind: "ok",
        code: commune.code_insee,
        stats: s.status === "fulfilled" ? s.value : null,
        statsError: s.status === "rejected" ? errorMessage(s.reason) : null,
        risques: r.status === "fulfilled" ? r.value : null,
      });
    });
    return () => ctrl.abort();
  }, [commune.code_insee]);

  if (state.kind === "loading") {
    return (
      <p className="note" role="status" aria-busy="true">
        Lecture des ventes et des risques {deNom(commune.nom_commune)}…
      </p>
    );
  }
  if (state.kind === "error") return <p className="alert" role="alert">{state.message}</p>;

  const groupes = state.stats?.groupes ?? [];
  const annees = [...new Set(groupes.map((g) => g.annee))].sort();
  const cell = (type: string, annee: number) => {
    const g = groupes.find((x) => x.type_local === type && x.annee === annee);
    if (!g) return <td className="r note">moins de 5 ventes</td>;
    return (
      <td className="r num">
        {eurosM2(g.prix_m2_median)}
        <br />
        <span className="note">
          {nombre(g.n_ventes)} ventes
          {g.prix_m2_q1 !== null && g.prix_m2_q3 !== null ? `, Q1 ${nombre(g.prix_m2_q1)} à Q3 ${nombre(g.prix_m2_q3)}` : ""}
        </span>
      </td>
    );
  };
  const r = state.risques;
  return (
    <div className="commune">
      <H>{commune.nom_commune}</H>
      {state.statsError && <p className="note">{state.statsError}</p>}
      {annees.length > 0 && (
        <div className="table-scroll">
          <table>
            <caption className="sr-only">Prix médian au mètre carré des ventes {deNom(commune.nom_commune)}, par année et type de bien</caption>
            <thead>
              <tr>
                <th scope="col">Année</th>
                <th scope="col" className="r">Appartements</th>
                <th scope="col" className="r">Maisons</th>
              </tr>
            </thead>
            <tbody>
              {annees.map((a) => (
                <tr key={a}>
                  <th scope="row" className="num">{a === 2021 ? "2021 (2e sem.)" : a}</th>
                  {cell("Appartement", a)}
                  {cell("Maison", a)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {r && (
        <dl className="facts">
          <div><dt>PPRI (inondation)</dt><dd>{ouiNon(r.ppri)}</dd></div>
          <div><dt>Territoire à risque d&apos;inondation (TRI)</dt><dd>{ouiNon(r.in_tri)}</dd></div>
          <div><dt>Arrêtés Cat-Nat, 10 ans</dt><dd className="num">{r.n_catnat_10ans ?? "inconnu"}</dd></div>
          <div>
            <dt>Argiles (IRIS de la commune)</dt>
            <dd>
              {Object.entries(r.rga_iris).length
                ? Object.entries(r.rga_iris).map(([k, n]) => `${k.replace("Exposition ", "")} : ${n}`).join(", ")
                : "inconnu"}
            </dd>
          </div>
        </dl>
      )}
      <p className="note">Sources : DVF géolocalisées (agrégats d&apos;au moins 5 ventes), Géorisques (GASPAR, RGA).</p>
    </div>
  );
}
