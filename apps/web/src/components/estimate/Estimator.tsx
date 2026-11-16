"use client";

/**
 * Estimer et comparer : un bien fictif, un ou deux lieux, la réponse de /estimate.
 * Les fiches (jauge, frise, waterfall) sont dans un chunk chargé à la première réponse.
 */
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { errorMessage, estimate } from "@/lib/api";
import { pointRequest, useStore } from "@/lib/store";
import type { Bien, Estimation } from "@/lib/types";
import { BienForm, DEFAULT_DRAFT, validateDraft, type BienDraft, type DraftErrors } from "./BienForm";
import { EMPTY_POSITION, PositionPicker, resolvePosition, type PositionDraft } from "./PositionPicker";
import { Pending } from "./Pending";
import styles from "./estimate.module.css";

const Results = lazy(() => import("./Results"));

export type SlotResult =
  | { kind: "idle" }
  | { kind: "loading"; startedAt: number }
  | { kind: "error"; message: string }
  | { kind: "ok"; est: Estimation; label: string };

export function Estimator() {
  const [draft, setDraft] = useState<BienDraft>(DEFAULT_DRAFT);
  const [errors, setErrors] = useState<DraftErrors>({});
  const [posA, setPosA] = useState<PositionDraft>(EMPTY_POSITION);
  const [posB, setPosB] = useState<PositionDraft>({ ...EMPTY_POSITION, mode: "commune" });
  const [compare, setCompare] = useState(false);
  const [posErr, setPosErr] = useState<{ A: string | null; B: string | null }>({ A: null, B: null });
  const [res, setRes] = useState<{ A: SlotResult; B: SlotResult }>({ A: { kind: "idle" }, B: { kind: "idle" } });
  const [bien, setBien] = useState<Bien | null>(null);
  const req = useStore(pointRequest);
  const ctrl = useRef<AbortController | null>(null);
  const resultsRef = useRef<HTMLDivElement>(null);

  // Un point choisi sur la carte devient la position du lieu A ou B.
  useEffect(() => {
    if (!req) return;
    const point = { lat: req.lat, lon: req.lon, label: req.label };
    if (req.slot === "A") setPosA((p) => ({ ...p, mode: "carte", point }));
    else {
      setCompare(true);
      setPosB((p) => ({ ...p, mode: "carte", point }));
    }
  }, [req]);

  useEffect(() => () => ctrl.current?.abort(), []);

  const run = async (slot: "A" | "B", b: Bien, pos: PositionDraft, signal: AbortSignal): Promise<void> => {
    const r = resolvePosition(pos);
    if (!r.ok) return;
    setRes((s) => ({ ...s, [slot]: { kind: "loading", startedAt: performance.now() } }));
    try {
      const est = await estimate(b, r.pos, { signal });
      const label = r.pos.kind === "adresse" ? `Adresse saisie, ${est.localisation.nom_commune}` : r.pos.label;
      setRes((s) => ({ ...s, [slot]: { kind: "ok", est, label } }));
    } catch (err) {
      if (signal.aborted) return;
      setRes((s) => ({ ...s, [slot]: { kind: "error", message: errorMessage(err) } }));
    }
  };

  const onSubmit = (e: React.FormEvent): void => {
    e.preventDefault();
    const v = validateDraft(draft);
    setErrors(v.errors);
    const ra = resolvePosition(posA);
    const rb = compare ? resolvePosition(posB) : null;
    setPosErr({ A: ra.ok ? null : ra.error, B: rb && !rb.ok ? rb.error : null });
    if (!v.bien || !ra.ok || (rb && !rb.ok)) return;
    ctrl.current?.abort();
    const c = new AbortController();
    ctrl.current = c;
    setBien(v.bien);
    setRes({ A: { kind: "idle" }, B: { kind: "idle" } });
    void run("A", v.bien, posA, c.signal);
    if (compare) void run("B", v.bien, posB, c.signal);
    resultsRef.current?.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
  };

  const busy = res.A.kind === "loading" || res.B.kind === "loading";
  const anyResult = res.A.kind !== "idle" || res.B.kind !== "idle";

  return (
    <div className={styles.estimator}>
      <form className={`panel ${styles.form}`} onSubmit={onSubmit} noValidate aria-label="Estimer un bien">
        <BienForm draft={draft} errors={errors} onChange={setDraft} />
        <PositionPicker slot="A" value={posA} error={posErr.A} onChange={setPosA} />
        <label className={styles.compareToggle}>
          <input type="checkbox" checked={compare} onChange={(e) => setCompare(e.target.checked)} />
          <span>Comparer avec un second lieu, pour le même bien</span>
        </label>
        {compare && <PositionPicker slot="B" value={posB} error={posErr.B} onChange={setPosB} />}
        <div className={styles.submitRow}>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {compare ? "Estimer et comparer" : "Estimer et projeter en 2050"}
          </button>
          <span className="note">Une estimation compte 5 demandes dans la limite de l&apos;API (60 par minute).</span>
        </div>
      </form>

      <div ref={resultsRef} className={styles.results} aria-live="polite" aria-busy={busy}>
        {!anyResult && (
          <p className="note">
            Décrivez un bien et choisissez un lieu : la fiche donnera le prix d&apos;aujourd&apos;hui en fourchette, sa projection 2050
            en euros constants, et ce qui reste inconnu.
          </p>
        )}
        {(["A", "B"] as const).map((slot) => {
          const r = res[slot];
          if (r.kind === "loading") return <Pending key={slot} slot={compare ? slot : null} startedAt={r.startedAt} />;
          if (r.kind === "error")
            return (
              <p key={slot} className="alert" role="alert">
                {compare ? `Lieu ${slot} : ` : ""}
                {r.message}
              </p>
            );
          return null;
        })}
        {bien && (res.A.kind === "ok" || res.B.kind === "ok") && (
          <Suspense fallback={<Pending slot={null} startedAt={performance.now()} />}>
            <Results a={res.A.kind === "ok" ? res.A : null} b={compare && res.B.kind === "ok" ? res.B : null} bien={bien} />
          </Suspense>
        )}
      </div>
    </div>
  );
}
