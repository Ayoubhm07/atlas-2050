"use client";

import { euros, pctSigne } from "@/lib/format";
import { ecartMedianes, groupScenarios } from "@/lib/scenarios";
import type { Estimation, Fourchette } from "@/lib/types";
import styles from "./estimate.module.css";

interface Ok {
  est: Estimation;
  label: string;
}

function Line({ title, fa, fb }: { title: string; fa: Fourchette | null | undefined; fb: Fourchette | null | undefined }) {
  if (!fa || !fb) {
    return (
      <tr>
        <th scope="row">{title}</th>
        <td colSpan={3} className="note">non calculé pour l&apos;un des deux lieux</td>
      </tr>
    );
  }
  return (
    <tr>
      <th scope="row">{title}</th>
      <td className="r num">{euros(fa.p50)}</td>
      <td className="r num">{euros(fb.p50)}</td>
      <td className="r num">{pctSigne(ecartMedianes(fa, fb))}</td>
    </tr>
  );
}

/** Deux relevés côte à côte : mêmes caractéristiques, deux lieux. */
export function CompareSummary({ a, b }: { a: Ok; b: Ok }) {
  const ga = groupScenarios(a.est);
  const gb = groupScenarios(b.est);
  return (
    <section className={`panel ${styles.summary}`} aria-labelledby="comparaison-titre">
      <h3 id="comparaison-titre">
        {a.est.localisation.nom_commune} et {b.est.localisation.nom_commune}, même bien
      </h3>
      <div className="table-scroll">
        <table>
          <caption className="sr-only">Valeurs médianes du même bien aux deux lieux</caption>
          <thead>
            <tr>
              <th scope="col">Médiane P50</th>
              <th scope="col" className="r">Lieu A</th>
              <th scope="col" className="r">Lieu B</th>
              <th scope="col" className="r">B par rapport à A</th>
            </tr>
          </thead>
          <tbody>
            <Line title="Aujourd'hui" fa={a.est.valeur} fb={b.est.valeur} />
            <Line title={`${a.est.horizon}, statu quo`} fa={ga.statuQuo?.valeur} fb={gb.statuQuo?.valeur} />
            <Line title={`${a.est.horizon}, rénové en D`} fa={ga.renovation?.valeur} fb={gb.renovation?.valeur} />
          </tbody>
        </table>
      </div>
      <p className="note">
        Écart entre médianes : les fourchettes des deux lieux se recouvrent souvent, voir les fiches (même échelle). Climat :{" "}
        <span className="tag tag-drias">indisponible (DRIAS)</span> pour les deux lieux.
      </p>
    </section>
  );
}
