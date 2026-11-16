"use client";

/**
 * Vue de droite : l'affiche SVG (rendue serveur) tant que la carte 3D n'a pas dessiné ses
 * premiers hexagones, puis la carte, chargée à la première intention (geste sur la vue,
 * bouton, réglage). Le JavaScript lourd (MapLibre, deck.gl, H3) n'est jamais dans le
 * chargement initial, et l'affiche reste en place si la carte ou l'API échoue.
 */
import { lazy, Suspense, useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { filtersStore, mapFocusRequest, mapIntentStore, mapStatusStore } from "@/lib/mapState";
import { useStore } from "@/lib/store";
import { Incognita } from "./Incognita";
import { SelectionCard } from "./SelectionCard";
import heroStyles from "../hero/hero.module.css";
import styles from "./map.module.css";

const loadMapView = (): Promise<typeof import("./MapView")> => import("./MapView");

const MapView = lazy((): Promise<{ default: () => React.ReactElement | null }> =>
  loadMapView().catch(() => {
    mapStatusStore.set({ status: "error", message: "La carte 3D n'a pas pu être chargée : l'affiche et le tableau restent disponibles." });
    return { default: () => null };
  }),
);

const noop = (): (() => void) => () => undefined;

interface Props {
  poster: ReactNode;
}

export function MapViewport({ poster }: Props) {
  // vrai seulement après l'hydratation : sans JavaScript, aucun bouton mort n'est rendu
  const hydrated = useSyncExternalStore(noop, () => true, () => false);
  const [clicked, setClicked] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const intent = useStore(mapIntentStore);
  const { status, message } = useStore(mapStatusStore);
  const filters = useStore(filtersStore);
  const view = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const wanted = clicked || intent > 0;
  const ready = status === "ready";

  // geste sur la vue = intention (pas le focus : le clavier passe par le bouton)
  useEffect(() => {
    const el = view.current;
    if (!el || wanted) return;
    const go = (): void => setClicked(true);
    const opts = { once: true, passive: true } as const;
    el.addEventListener("pointerdown", go, opts);
    el.addEventListener("wheel", go, opts);
    return () => {
      el.removeEventListener("pointerdown", go);
      el.removeEventListener("wheel", go);
    };
  }, [wanted]);

  useEffect(() => {
    if (wanted && status === "idle") mapStatusStore.set({ status: "loading", message: null });
  }, [wanted, status]);

  // le bouton disparaît quand la carte est prête : si le clavier y était (ou si « Voir »
  // l'a demandé), le focus passe sur la carte. Abonnement direct au magasin : on décide
  // avant que React ne retire le bouton du DOM.
  useEffect(
    () =>
      mapStatusStore.subscribe(() => {
        if (mapStatusStore.get().status !== "ready") return;
        if (document.activeElement !== button.current && !mapFocusRequest.get()) return;
        mapFocusRequest.set(false);
        view.current?.querySelector<HTMLCanvasElement>("canvas.maplibregl-canvas")?.focus();
      }),
    [],
  );

  const onButton = (): void => {
    if (status === "error") {
      setAttempt((a) => a + 1);
      mapStatusStore.set({ status: "loading", message: null });
    }
    setClicked(true);
  };

  const label = status === "error" ? "Réessayer la carte 3D" : status === "loading" ? "Relief en chargement…" : "Soulever le relief";

  return (
    <div ref={view} className={heroStyles.view} aria-label="Carte du relevé" role="region">
      <div className={heroStyles.posterBox} data-hidden={ready ? "true" : "false"} aria-hidden={ready}>
        {poster}
      </div>
      {wanted && status !== "error" && (
        <div className={styles.mapWrap} data-ready={ready ? "true" : "false"}>
          <Suspense fallback={null}>
            <MapView key={attempt} />
          </Suspense>
        </div>
      )}
      {hydrated && !ready && (
        <button
          ref={button}
          type="button"
          className={`btn btn-primary ${styles.raise}`}
          aria-disabled={status === "loading" || undefined}
          onPointerEnter={() => void loadMapView()}
          onFocus={() => void loadMapView()}
          onClick={status === "loading" ? undefined : onButton}
        >
          {label}
        </button>
      )}
      {(status === "loading" || message) && (
        <p className={styles.chip} role="status">
          {status === "loading" && <span className={styles.dot} aria-hidden="true" />}
          {status === "loading" ? "Chargement de la carte 3D et des hexagones" : message}
        </p>
      )}
      {ready && filters.temps === "2050" && <Incognita />}
      {ready && <SelectionCard />}
    </div>
  );
}
