"use client";

import type { Bien, Dpe, TypeLocal } from "@/lib/types";
import styles from "./estimate.module.css";

export interface BienDraft {
  type_local: TypeLocal;
  surface: string;
  pieces: string;
  surface_terrain: string;
  dependances: string;
  dpe: Dpe | "";
}

export const DEFAULT_DRAFT: BienDraft = {
  type_local: "Maison",
  surface: "96",
  pieces: "4",
  surface_terrain: "500",
  dependances: "0",
  dpe: "",
};

export type DraftErrors = Partial<Record<keyof BienDraft, string>>;

function parseNum(raw: string): number | null {
  const v = Number(raw.replace(",", ".").trim());
  return raw.trim() === "" || !Number.isFinite(v) ? null : v;
}

/** Mêmes bornes que l'API (EstimateQuery) : l'erreur est dite avant l'envoi. */
export function validateDraft(d: BienDraft): { bien: Bien | null; errors: DraftErrors } {
  const errors: DraftErrors = {};
  const surface = parseNum(d.surface);
  const pieces = parseNum(d.pieces);
  const terrain = parseNum(d.surface_terrain);
  const dep = parseNum(d.dependances);
  if (surface === null || surface < 9 || surface > 1000) errors.surface = "Entre 9 et 1 000 m².";
  if (pieces === null || !Number.isInteger(pieces) || pieces < 1 || pieces > 30) errors.pieces = "Nombre entier de 1 à 30.";
  if (d.type_local === "Maison" && d.surface_terrain.trim() !== "" && (terrain === null || terrain < 0 || terrain > 10000)) {
    errors.surface_terrain = "Entre 0 et 10 000 m² : le modèle n'a vu aucune maison de plus d'un hectare.";
  }
  if (dep === null || !Number.isInteger(dep) || dep < 0 || dep > 10) errors.dependances = "Nombre entier de 0 à 10.";
  if (Object.keys(errors).length > 0) return { bien: null, errors };
  return {
    bien: {
      type_local: d.type_local,
      surface: surface as number,
      pieces: pieces as number,
      surface_terrain: d.type_local === "Maison" && terrain !== null ? terrain : null,
      dependances: dep as number,
      dpe: d.dpe === "" ? null : d.dpe,
    },
    errors,
  };
}

interface Props {
  draft: BienDraft;
  errors: DraftErrors;
  onChange: (next: BienDraft) => void;
}

function NumField(props: {
  name: keyof BienDraft;
  label: string;
  unit?: string;
  draft: BienDraft;
  errors: DraftErrors;
  onChange: (next: BienDraft) => void;
  inputMode?: "numeric" | "decimal";
}) {
  const { name, label, unit, draft, errors, onChange } = props;
  const err = errors[name];
  const id = `bien-${name}`;
  return (
    <label className="field" htmlFor={id}>
      <span>
        {label}
        {unit ? <span className="note"> ({unit})</span> : null}
      </span>
      <input
        id={id}
        type="text"
        inputMode={props.inputMode ?? "numeric"}
        value={draft[name] as string}
        aria-invalid={err ? true : undefined}
        aria-describedby={err ? `${id}-err` : undefined}
        onChange={(e) => onChange({ ...draft, [name]: e.target.value })}
      />
      {err && (
        <span id={`${id}-err`} className={styles.err}>
          {err}
        </span>
      )}
    </label>
  );
}

export function BienForm({ draft, errors, onChange }: Props) {
  return (
    <fieldset className={styles.bien}>
      <legend>Le bien (fictif : aucune vente réelle n&apos;est consultée)</legend>
      <div className="seg" style={{ gridColumn: "1 / -1" }}>
        {(["Maison", "Appartement"] as const).map((t) => (
          <label key={t}>
            <input type="radio" name="type_local" value={t} checked={draft.type_local === t} onChange={() => onChange({ ...draft, type_local: t })} />
            <span>{t}</span>
          </label>
        ))}
      </div>
      <NumField name="surface" label="Surface habitable" unit="m²" inputMode="decimal" draft={draft} errors={errors} onChange={onChange} />
      <NumField name="pieces" label="Pièces principales" draft={draft} errors={errors} onChange={onChange} />
      {draft.type_local === "Maison" && (
        <NumField name="surface_terrain" label="Terrain" unit="m², facultatif" inputMode="decimal" draft={draft} errors={errors} onChange={onChange} />
      )}
      <NumField name="dependances" label="Dépendances" draft={draft} errors={errors} onChange={onChange} />
      <label className="field" htmlFor="bien-dpe">
        <span>
          Étiquette DPE <span className="note">(facultatif)</span>
        </span>
        <select id="bien-dpe" value={draft.dpe} onChange={(e) => onChange({ ...draft, dpe: e.target.value as Dpe | "" })}>
          <option value="">Inconnue</option>
          {(["A", "B", "C", "D", "E", "F", "G"] as const).map((d) => (
            <option key={d} value={d}>
              Classe {d}
            </option>
          ))}
        </select>
      </label>
    </fieldset>
  );
}
