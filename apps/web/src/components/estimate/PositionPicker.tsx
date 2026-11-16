"use client";

import { CommuneSearch } from "@/components/CommuneSearch";
import { coordonnees } from "@/lib/format";
import styles from "./estimate.module.css";

export type Mode = "adresse" | "commune" | "carte";

export interface PositionDraft {
  mode: Mode;
  address: string;
  point: { lat: number; lon: number; label: string } | null;
  commune: { lat: number; lon: number; label: string } | null;
}

export const EMPTY_POSITION: PositionDraft = { mode: "adresse", address: "", point: null, commune: null };

const MODES: readonly { v: Mode; l: string }[] = [
  { v: "adresse", l: "Adresse" },
  { v: "commune", l: "Commune" },
  { v: "carte", l: "Point de la carte" },
];

interface Props {
  slot: "A" | "B";
  value: PositionDraft;
  error: string | null;
  onChange: (next: PositionDraft) => void;
}

export function PositionPicker({ slot, value, error, onChange }: Props) {
  const name = `mode-${slot}`;
  const errId = `pos-${slot}-err`;
  return (
    <fieldset className={styles.position} aria-describedby={error ? errId : undefined}>
      <legend>{slot === "A" ? "Où ?" : "Second lieu (B)"}</legend>
      <div className="seg">
        {MODES.map((m) => (
          <label key={m.v}>
            <input type="radio" name={name} value={m.v} checked={value.mode === m.v} onChange={() => onChange({ ...value, mode: m.v })} />
            <span>{m.l}</span>
          </label>
        ))}
      </div>
      {value.mode === "adresse" && (
        <label className="field" htmlFor={`adresse-${slot}`}>
          <span>Adresse en Gironde</span>
          <input
            id={`adresse-${slot}`}
            type="text"
            autoComplete="street-address"
            maxLength={200}
            placeholder="ex. 12 cours de l'Intendance, Bordeaux"
            value={value.address}
            onChange={(e) => onChange({ ...value, address: e.target.value })}
          />
          <span className="note">
            Envoyée à l&apos;API locale dans le corps d&apos;une requête (jamais dans une adresse web), géocodée par la Base Adresse
            Nationale, ni renvoyée ni journalisée.
          </span>
        </label>
      )}
      {value.mode === "commune" && (
        <>
          <CommuneSearch
            label="Commune"
            onSelect={(h) => onChange({ ...value, commune: { lat: h.lat, lon: h.lon, label: `${h.nom_commune} (point intérieur de la commune)` } })}
            onEdit={() => value.commune && onChange({ ...value, commune: null })}
          />
          {value.commune && <p className="note">Position retenue : {value.commune.label}, {coordonnees(value.commune.lat, value.commune.lon)}.</p>}
        </>
      )}
      {value.mode === "carte" &&
        (value.point ? (
          <p className="note">Position retenue : {value.point.label}.</p>
        ) : (
          <p className="note">
            Touchez la carte plus haut, puis « {slot === "A" ? "Estimer un bien ici" : "Comparer avec ce lieu"} ». <a href="#carte">Aller à la carte</a>
          </p>
        ))}
      {error && (
        <p id={errId} className={styles.err} role="alert">
          {error}
        </p>
      )}
    </fieldset>
  );
}

/** Position prête à l'envoi, ou message d'erreur. */
export function resolvePosition(p: PositionDraft):
  | { ok: true; pos: { kind: "point"; lat: number; lon: number; label: string } | { kind: "adresse"; address: string } }
  | { ok: false; error: string } {
  if (p.mode === "adresse") {
    const a = p.address.trim();
    if (a.length < 5) return { ok: false, error: "Saisir une adresse d'au moins 5 caractères." };
    return { ok: true, pos: { kind: "adresse", address: a } };
  }
  const pt = p.mode === "commune" ? p.commune : p.point;
  if (!pt) return { ok: false, error: p.mode === "commune" ? "Choisir une commune dans la liste." : "Choisir un point sur la carte." };
  return { ok: true, pos: { kind: "point", ...pt } };
}
