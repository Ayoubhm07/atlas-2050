"use client";

import { domaine, groupScenarios } from "@/lib/scenarios";
import type { Bien, Estimation, Fourchette } from "@/lib/types";
import { CompareSummary } from "./CompareSummary";
import { Sheet } from "./Sheet";
import styles from "./estimate.module.css";

interface Ok {
  est: Estimation;
  label: string;
}

function fourchettes(est: Estimation): Fourchette[] {
  const g = groupScenarios(est);
  return [
    est.prix_m2,
    ...[g.statuQuo, g.renovation, ...g.sensibilites].flatMap((s) => (s?.prix_m2 ? [s.prix_m2] : [])),
    ...g.sensibilites.flatMap((s) => (s.sensibilite ? [s.sensibilite.avec_voisinage, s.sensibilite.sans_voisinage] : [])),
  ];
}

/** Une fiche, ou deux fiches sur une même règle (comparaison honnête : même échelle). */
export default function Results({ a, b, bien }: { a: Ok | null; b: Ok | null; bien: Bien }) {
  if (a && b) {
    const dom = domaine([...fourchettes(a.est), ...fourchettes(b.est)]);
    return (
      <div className={styles.compare}>
        <CompareSummary a={a} b={b} />
        <div className={styles.pair}>
          <Sheet est={a.est} bien={bien} label={a.label} slot="A" domain={dom} />
          <Sheet est={b.est} bien={bien} label={b.label} slot="B" domain={dom} />
        </div>
      </div>
    );
  }
  const one = a ?? b;
  if (!one) return null;
  return <Sheet est={one.est} bien={bien} label={one.label} slot={a ? (b ? "A" : null) : "B"} />;
}
