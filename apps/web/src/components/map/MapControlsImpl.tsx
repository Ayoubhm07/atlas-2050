"use client";

/**
 * Réglages de la carte : type, DPE, temps (années réelles, puis 2050 en blanc), sol des
 * argiles, légende, recherche de commune. Toucher un réglage charge la carte 3D.
 */
import { useState } from "react";
import { CommunePanel } from "@/components/CommunePanel";
import { CommuneSearch } from "@/components/CommuneSearch";
import { eurosM2, nombre, pct } from "@/lib/format";
import { filtersStore, legendStore, mapIntentStore, mapStatusStore, TEMPS_LABELS, type Filters, type Temps } from "@/lib/mapState";
import { legend } from "@/lib/ramp";
import { flyRequest, nextNonce, useStore } from "@/lib/store";
import type { CommuneHit, DpeFiltre, TypeFiltre } from "@/lib/types";
import { SOL_COLORS } from "./mapStyle";
import styles from "./map.module.css";

export interface Props {
  initial: { breaks: number[]; nCells: number; nVentes: number } | null;
  partDpe: number;
}

const TEMPS: readonly Temps[] = ["tous", "2021", "2022", "2023", "2024", "2050"];
const TYPES: readonly { v: TypeFiltre; l: string }[] = [
  { v: "tous", l: "Tous" },
  { v: "Maison", l: "Maisons" },
  { v: "Appartement", l: "Appartements" },
];
const DPES: readonly DpeFiltre[] = ["tous", "A", "B", "C", "D", "E", "F", "G"];

function update(patch: Partial<Filters>): void {
  filtersStore.set((f) => ({ ...f, ...patch }));
  if (mapStatusStore.get().status === "idle") mapIntentStore.set((n) => n + 1);
}

export default function MapControlsImpl({ initial, partDpe }: Props) {
  const f = useStore(filtersStore);
  const live = useStore(legendStore);
  const [commune, setCommune] = useState<CommuneHit | null>(null);
  const shown = live ?? (initial ? { ...initial, res: 7 as const, loading: false, error: null } : null);
  const items = shown ? legend(shown.breaks, eurosM2) : [];

  const onCommune = (h: CommuneHit): void => {
    setCommune(h);
    flyRequest.set({ lon: h.lon, lat: h.lat, zoom: 11.2, nonce: nextNonce() });
    if (mapStatusStore.get().status === "idle") mapIntentStore.set((n) => n + 1);
  };

  return (
    <div className={styles.controls}>
      <fieldset>
        <legend>Temps : année des ventes, puis 2050</legend>
        <div className="seg seg-temps">
          {TEMPS.map((t) => (
            <label key={t} className={t === "2050" ? "seg-2050" : undefined}>
              <input type="radio" name="temps" value={t} checked={f.temps === t} onChange={() => update({ temps: t })} />
              <span>{TEMPS_LABELS[t]}</span>
            </label>
          ))}
        </div>
      </fieldset>

      <div className={styles.row2}>
        <label className="field" htmlFor="carte-type">
          <span>Type de bien</span>
          <select id="carte-type" value={f.type} onChange={(e) => update({ type: e.target.value as TypeFiltre })}>
            {TYPES.map((t) => (
              <option key={t.v} value={t.v}>{t.l}</option>
            ))}
          </select>
        </label>
        <label className="field" htmlFor="carte-dpe">
          <span>Étiquette DPE des ventes</span>
          <select id="carte-dpe" value={f.dpe} onChange={(e) => update({ dpe: e.target.value as DpeFiltre })}>
            {DPES.map((d) => (
              <option key={d} value={d}>{d === "tous" ? "Toutes" : `Classe ${d}`}</option>
            ))}
          </select>
        </label>
      </div>
      {f.dpe !== "tous" && (
        <p className="note">
          Un DPE n&apos;est rattaché qu&apos;à {pct(partDpe)} des ventes, surtout des maisons : peu d&apos;hexagones atteignent 5 ventes.
        </p>
      )}

      <div>
        <p className="legend-title" id="legende-prix">
          Prix médian au m²,{" "}
          {shown && !shown.error ? `${nombre(shown.nCells)} hexagones r${shown.res}, ${nombre(shown.nVentes)} ventes` : "données indisponibles"}
          {f.temps === "2050" ? " (repère 2021 à 2024)" : ""}
        </p>
        {shown?.loading && <p className="note" role="status">Chargement des hexagones…</p>}
        {shown?.error && <p className="alert" role="alert">{shown.error}</p>}
        {shown && shown.nCells === 0 && !shown.loading && !shown.error && (
          <p className="note" role="status">Aucun hexagone d&apos;au moins 5 ventes pour ces réglages.</p>
        )}
        <ul className={styles.legend} aria-labelledby="legende-prix">
          {items.map((it) => (
            <li key={it.label}>
              <span className={styles.swatch} style={{ background: it.color }} aria-hidden="true" />
              <span className="num">{it.label}</span>
            </li>
          ))}
        </ul>
        <p className="note">Classes par quantiles des hexagones affichés ; hauteur proportionnelle au prix.</p>
      </div>

      <div>
        <label className={styles.check}>
          <input type="checkbox" checked={f.sol} onChange={(e) => update({ sol: e.target.checked })} />
          <span>Sol : exposition aux argiles (RGA)</span>
        </label>
        <ul className={styles.legend} aria-label="Légende du sol">
          <li><span className={styles.swatch} style={{ background: SOL_COLORS.forte }} aria-hidden="true" />forte</li>
          <li><span className={styles.swatch} style={{ background: SOL_COLORS.moyenne }} aria-hidden="true" />moyenne</li>
          <li><span className={`${styles.swatch} hatched`} style={{ border: "1px solid var(--rule)" }} aria-hidden="true" />inconnue</li>
        </ul>
        <p className="note">
          Au centroïde de chaque IRIS (Géorisques). C&apos;est le seul risque que l&apos;API cartographie ; inondation et Cat-Nat
          sont communaux et figurent dans la fiche.
        </p>
      </div>

      <CommuneSearch label="Aller à une commune" onSelect={onCommune} />
      {commune && <CommunePanel commune={commune} />}
    </div>
  );
}
