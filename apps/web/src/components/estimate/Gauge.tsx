"use client";

/**
 * « La fourchette, pas le chiffre » : chaque ligne est une fourchette P10-P90 renvoyée par
 * l'API, sur une même règle en euros. Les scénarios climatiques sont des cartouches
 * hachurés sans aucune barre : l'API ne les chiffre pas (DRIAS indisponible).
 */
import type { CSSProperties } from "react";
import { dateLongue, euros, eurosM2 } from "@/lib/format";
import { domaine, groupScenarios, RISK_LABELS, riskOf } from "@/lib/scenarios";
import type { Estimation, Fourchette } from "@/lib/types";
import styles from "./estimate.module.css";

/** Règle en €/m² (seule unité commune à toutes les lignes de l'API) ; valeur en texte. */
interface Row {
  key: string;
  label: string;
  f: Fourchette | null;
  v: Fourchette | null;
  tone: "actuel" | "futur" | "sens" | "borne" | "drias";
  note?: string;
}

export function gaugeRows(est: Estimation): Row[] {
  const g = groupScenarios(est);
  const rows: Row[] = [
    { key: "actuel", label: `Date de valeur, ${dateLongue(est.date_valeur)} (DPE au mix moyen)`, f: est.prix_m2, v: est.valeur, tone: "actuel" },
  ];
  if (g.statuQuo?.prix_m2) rows.push({ key: "sq", label: g.statuQuo.libelle, f: g.statuQuo.prix_m2, v: g.statuQuo.valeur, tone: "futur" });
  if (g.renovation?.prix_m2) rows.push({ key: "reno", label: g.renovation.libelle, f: g.renovation.prix_m2, v: g.renovation.valeur, tone: "futur" });
  for (const s of g.sensibilites) {
    rows.push({ key: s.id, label: s.libelle, f: s.prix_m2, v: s.valeur, tone: "sens", note: RISK_LABELS[riskOf(s)] });
    if (s.sensibilite) {
      rows.push({ key: `${s.id}-avec`, label: "borne avec contrôle du voisinage", f: s.sensibilite.avec_voisinage, v: null, tone: "borne" });
      rows.push({ key: `${s.id}-sans`, label: "borne sans contrôle du voisinage", f: s.sensibilite.sans_voisinage, v: null, tone: "borne" });
    }
  }
  for (const c of g.climat) rows.push({ key: c.id, label: c.libelle, f: null, v: null, tone: "drias", note: c.message ?? undefined });
  return rows;
}

function pos(v: number, [lo, hi]: [number, number]): number {
  return ((v - lo) / (hi - lo)) * 100;
}

export function Gauge({ est, domain }: { est: Estimation; domain?: [number, number] }) {
  const rows = gaugeRows(est);
  const dom = domain ?? domaine(rows.flatMap((r) => (r.f ? [r.f] : [])));
  const ticks = Array.from({ length: 5 }, (_, i) => dom[0] + ((dom[1] - dom[0]) * i) / 4);
  return (
    <div className={styles.gauge}>
      <ol className={styles.gaugeRows}>
        {rows.map((r, i) => (
          <li key={r.key} className={styles.gaugeRow} data-tone={r.tone}>
            <div className={styles.gaugeLabel}>
              <span>{r.label}</span>
              {r.f && r.v ? (
                <span className="num">
                  <strong>{euros(r.v.p50)}</strong> <span className="note">de {euros(r.v.p10)} à {euros(r.v.p90)}, médiane {eurosM2(r.f.p50)}</span>
                </span>
              ) : r.f ? (
                <span className="num note">
                  médiane {eurosM2(r.f.p50)}, de {eurosM2(r.f.p10)} à {eurosM2(r.f.p90)}
                </span>
              ) : (
                <span className="tag tag-drias">indisponible (DRIAS)</span>
              )}
            </div>
            {r.f ? (
              <div className={styles.track} aria-hidden="true">
                <span
                  className={styles.band}
                  style={
                    {
                      left: `${pos(r.f.p10, dom)}%`,
                      width: `${pos(r.f.p90, dom) - pos(r.f.p10, dom)}%`,
                      transformOrigin: `${((r.f.p50 - r.f.p10) / Math.max(1, r.f.p90 - r.f.p10)) * 100}% 50%`,
                      animationDelay: `${i * 70}ms`,
                    } as CSSProperties
                  }
                />
                <span className={styles.median} style={{ left: `${pos(r.f.p50, dom)}%`, animationDelay: `${i * 70}ms` }} />
              </div>
            ) : (
              <div className={`${styles.track} ${styles.trackDrias}`} aria-hidden="true">
                <span>non chiffré</span>
              </div>
            )}
            {r.tone === "drias" && r.note && <p className="note">{r.note}</p>}
          </li>
        ))}
      </ol>
      <div className={styles.axis} aria-hidden="true">
        {ticks.map((t) => (
          <span key={t} className="num" style={{ left: `${pos(t, dom)}%` }}>
            {eurosM2(Math.round(t / 100) * 100)}
          </span>
        ))}
      </div>
      <p className="note">
        Barre : de P10 à P90 (8 chances sur 10 d&apos;être dedans, selon les erreurs du modèle). Trait : médiane P50. Euros constants,
        sans tendance de marché.
      </p>
    </div>
  );
}
