"use client";

/**
 * Carte 3D, chargée en différé (chunk séparé) : MapLibre pour le sol (nos tuiles
 * Martin), deck.gl pour les colonnes hexagonales (hauteur et couleur = prix médian réel).
 * Le relief se soulève à l'ouverture ; les années glissent l'une dans l'autre ; à 2050
 * la carte se couvre de hachures (aucune valeur par hexagone n'existe pour 2050).
 */
import { MapboxOverlay } from "@deck.gl/mapbox";
import { PathLayer, SolidPolygonLayer } from "@deck.gl/layers";
import * as maplibregl from "maplibre-gl";
import type { Map as MlMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef } from "react";
import { errorMessage } from "@/lib/api";
import { GIRONDE_BBOX, R9_MIN_ZOOM, type Bbox } from "@/lib/geo";
import { loadR7, loadR9, type HexDatum } from "@/lib/hexdata";
import {
  filtersStore,
  legendStore,
  mapStatusStore,
  selectionStore,
  visibleCellsStore,
  type Filters,
} from "@/lib/mapState";
import { colorOf, quantileBreaks } from "@/lib/ramp";
import { flyRequest } from "@/lib/store";
import { atlasStyle, hatchImage, MAP_LOCALE } from "./mapStyle";
import styles from "./map.module.css";

// Worker MapLibre servi depuis public/ (scripts/copy-maplibre-worker.mjs)
maplibregl.setWorkerUrl(`/vendor/maplibre-gl-worker-${maplibregl.getVersion()}.mjs`);

const ELEV = { 7: 0.85, 9: 0.2 } as const;
const GHOST: [number, number, number, number] = [236, 230, 214, 34];
const INTRO_MS = 2000;

/** Valeur affichée : l'année choisie ; à 2050, le fantôme des valeurs 2021-2024. */
function displayed(d: HexDatum, f: Filters): { p: number; n: number } | undefined {
  return d.vals[f.temps === "2050" ? "tous" : f.temps];
}

function viewBbox(map: MlMap): Bbox {
  const b = map.getBounds();
  return [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()];
}

export default function MapView() {
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = box.current;
    if (!container) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const coarse = window.matchMedia("(pointer: coarse)").matches;

    let map: MlMap;
    try {
      map = new maplibregl.Map({
        container,
        style: atlasStyle(window.location.origin),
        bounds: [GIRONDE_BBOX[0], GIRONDE_BBOX[1], GIRONDE_BBOX[2], GIRONDE_BBOX[3]],
        fitBoundsOptions: { padding: { top: 40, bottom: 24, left: 70, right: 24 } },
        maxBounds: [-2.6, 43.4, 1.6, 46.4],
        minZoom: 6.5,
        maxZoom: 14.5,
        maxPitch: 70,
        attributionControl: false,
        cooperativeGestures: coarse,
        locale: MAP_LOCALE,
      });
    } catch {
      mapStatusStore.set({ status: "error", message: "WebGL indisponible sur cet appareil : l'affiche et le tableau restent disponibles." });
      return;
    }

    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");
    map.addControl(
      new maplibregl.AttributionControl({
        compact: true,
        customAttribution: "Contours IGN-INSEE (Contours IRIS) · ventes DVF (DGFiP, Etalab) · MapLibre, deck.gl, H3",
      }),
      "bottom-right",
    );
    const canvas = map.getCanvas();
    canvas.setAttribute(
      "aria-label",
      "Carte 3D des prix médians au mètre carré par hexagone. Flèches : déplacer ; plus et moins : zoomer ; Maj et flèches : incliner et tourner. Le tableau sous la carte donne les mêmes données.",
    );

    const overlay = new MapboxOverlay({ interleaved: false, layers: [] });
    map.addControl(overlay as unknown as maplibregl.IControl);
    // le canvas de deck.gl n'est qu'une surcouche : hors de l'ordre de tabulation
    const deckCanvas = container.querySelector<HTMLCanvasElement>("canvas#deckgl-overlay");
    deckCanvas?.setAttribute("tabindex", "-1");
    deckCanvas?.setAttribute("aria-hidden", "true");

    let data: HexDatum[] = [];
    let res: 7 | 9 = 7;
    let elevMul = reduced ? 1 : 0;
    let alive = true;
    let drawn = false; // premiers hexagones dessinés : l'affiche peut s'effacer
    let ctrl: AbortController | null = null;
    let raf = 0;

    let breaks: number[] = [];

    const render = (): void => {
      const f = filtersStore.get();
      const sel = selectionStore.get();
      const selected = sel?.hex ? data.find((d) => d.h3 === sel.hex?.h3) : undefined;
      const ghost = f.temps === "2050";
      const layers = [
        new SolidPolygonLayer<HexDatum>({
          id: "hexagones",
          data,
          extruded: true,
          pickable: true,
          autoHighlight: !ghost,
          highlightColor: [255, 236, 170, 120],
          getPolygon: (d) => d.polygon,
          getElevation: (d) => (displayed(d, f)?.p ?? 0) * ELEV[res],
          elevationScale: elevMul,
          getFillColor: (d) => {
            const v = displayed(d, f);
            if (!v) return [0, 0, 0, 0];
            if (ghost) return GHOST;
            const [r, g, b] = colorOf(v.p, breaks);
            return [r, g, b, 236];
          },
          material: { ambient: 0.55, diffuse: 0.6, shininess: 24, specularColor: [60, 52, 40] },
          updateTriggers: { getElevation: [f.temps, res], getFillColor: [f.temps, breaks.join(",")] },
          transitions: reduced ? {} : { getElevation: { duration: 900 }, getFillColor: { duration: 600 } },
        }),
        ...(selected
          ? [
              new PathLayer<HexDatum>({
                id: "selection",
                data: [selected],
                getPath: (d) => {
                  const z = (displayed(d, f)?.p ?? 0) * ELEV[res] * elevMul + 2;
                  const ring = d.polygon.map(([x, y]) => [x, y, z] as [number, number, number]);
                  return [...ring, ring[0] ?? [0, 0, 0]];
                },
                getColor: [255, 211, 107, 255],
                getWidth: 3,
                widthUnits: "pixels",
              }),
            ]
          : []),
      ];
      overlay.setProps({ layers });
    };

    /** Couches + légende + tableau accessible (pas à chaque image de l'ouverture). */
    const refresh = (): void => {
      const f = filtersStore.get();
      const values = data.map((d) => displayed(d, f)?.p).filter((p): p is number => p !== undefined);
      breaks = quantileBreaks(values);
      render();
      legendStore.set({
        breaks,
        nCells: values.length,
        nVentes: data.reduce((s, d) => s + (displayed(d, f)?.n ?? 0), 0),
        res,
        loading: false,
        error: null,
      });
      publishVisible();
    };

    const publishVisible = (): void => {
      const f = filtersStore.get();
      const [w, s, e, n] = viewBbox(map);
      const cells = data
        .flatMap((d) => {
          const v = displayed(d, f);
          return v && d.lon >= w && d.lon <= e && d.lat >= s && d.lat <= n ? [{ h3: d.h3, prix: v.p, n: v.n, lon: d.lon, lat: d.lat }] : [];
        })
        .sort((a, b) => b.prix - a.prix);
      visibleCellsStore.set(cells);
    };

    const load = async (): Promise<void> => {
      ctrl?.abort();
      const c = new AbortController();
      ctrl = c;
      const f = filtersStore.get();
      const wantRes: 7 | 9 = map.getZoom() >= R9_MIN_ZOOM ? 9 : 7;
      const prev = legendStore.get();
      legendStore.set(prev ? { ...prev, loading: true, error: null } : { breaks: [], nCells: 0, nVentes: 0, res: wantRes, loading: true, error: null });
      try {
        const annee = f.temps === "2050" ? "tous" : f.temps;
        const next = wantRes === 7 ? await loadR7(f.type, f.dpe, c.signal) : await loadR9(viewBbox(map), f.type, f.dpe, annee, c.signal);
        if (!alive || c.signal.aborted) return;
        data = next;
        res = wantRes;
        refresh();
        if (!drawn) {
          drawn = true;
          mapStatusStore.set({ status: "ready", message: null });
        }
      } catch (err) {
        if (!alive || c.signal.aborted) return;
        if (!drawn) {
          // sans données, pas de carte vide : l'affiche reste, l'erreur est dite dans la vue
          mapStatusStore.set({ status: "error", message: `Hexagones indisponibles : ${errorMessage(err)}` });
          return;
        }
        const p = legendStore.get();
        legendStore.set({ ...(p ?? { breaks: [], nCells: 0, nVentes: 0, res: wantRes }), loading: false, error: errorMessage(err) });
      }
    };

    const intro = (): void => {
      // un cadrage demandé avant que la carte ne soit prête (commune, tableau) l'emporte
      const pending = flyRequest.get();
      const end = pending
        ? { pitch: 50, bearing: -14, zoom: pending.zoom, center: [pending.lon, pending.lat] as [number, number] }
        : { pitch: 50, bearing: -14, zoom: map.getZoom() + 0.15 };
      if (reduced) {
        map.jumpTo(end);
        return;
      }
      map.easeTo({ ...end, duration: INTRO_MS + 400, easing: (t) => 1 - Math.pow(1 - t, 3) });
      const t0 = performance.now();
      const step = (now: number): void => {
        const t = Math.min(1, Math.max(0, (now - t0) / INTRO_MS));
        elevMul = 1 - Math.pow(1 - t, 3);
        if (t < 1) raf = requestAnimationFrame(step); // planifier avant de dessiner
        render();
      };
      raf = requestAnimationFrame(step);
    };

    // motif des IRIS « inconnue » : ajouté dès que le style est lu, avant les tuiles
    map.once("style.load", () => {
      if (!map.hasImage("hachures")) map.addImage("hachures", hatchImage());
    });
    map.on("load", () => {
      // crédits repliés sur petit écran (le bouton « i » les rouvre)
      if (window.innerWidth < 640) {
        const attrib = container.querySelector(".maplibregl-ctrl-attrib");
        attrib?.classList.remove("maplibregl-compact-show");
        attrib?.removeAttribute("open");
      }
      void load().then(() => alive && drawn && intro());
    });
    map.on("error", (e) => {
      const msg = (e as { error?: { message?: string } }).error?.message ?? "";
      if (/tiles|Failed to fetch|404|502|503/i.test(msg)) {
        mapStatusStore.set((s) => ({ ...s, message: "Contours du sol indisponibles (serveur de tuiles Martin arrêté ?) : les hexagones restent justes." }));
      }
    });

    let lastRes: 7 | 9 = 7;
    let moveTimer = 0;
    map.on("moveend", () => {
      window.clearTimeout(moveTimer);
      moveTimer = window.setTimeout(() => {
        const wantRes: 7 | 9 = map.getZoom() >= R9_MIN_ZOOM ? 9 : 7;
        if (wantRes === 9 || wantRes !== lastRes) void load();
        else publishVisible();
        lastRes = wantRes;
      }, 220);
    });

    map.on("click", (e) => {
      const picked = overlay.pickObject({ x: e.point.x, y: e.point.y, radius: 2 }) as { object?: HexDatum } | null;
      const f = filtersStore.get();
      const d = picked?.object;
      const v = d ? displayed(d, f) : undefined;
      selectionStore.set({
        lon: e.lngLat.lng,
        lat: e.lngLat.lat,
        hex: d && v ? { h3: d.h3, res, prix: v.p, n: v.n, temps: f.temps } : null,
      });
    });

    let prevFilters = filtersStore.get();
    const unsubFilters = filtersStore.subscribe(() => {
      const f = filtersStore.get();
      if (f.sol !== prevFilters.sol) {
        const vis = f.sol ? "visible" : "none";
        if (map.getLayer("sol-argiles")) map.setLayoutProperty("sol-argiles", "visibility", vis);
        if (map.getLayer("sol-inconnu")) map.setLayoutProperty("sol-inconnu", "visibility", vis);
      }
      const needsData = f.type !== prevFilters.type || f.dpe !== prevFilters.dpe || (res === 9 && f.temps !== prevFilters.temps);
      prevFilters = f;
      if (needsData) void load();
      else refresh();
    });
    const unsubSel = selectionStore.subscribe(render);
    const unsubFly = flyRequest.subscribe(() => {
      const r = flyRequest.get();
      if (!r) return;
      const opts = { center: [r.lon, r.lat] as [number, number], zoom: r.zoom, pitch: 50 };
      if (reduced) map.jumpTo(opts);
      else map.flyTo({ ...opts, duration: 1600, essential: false });
    });

    return () => {
      alive = false;
      ctrl?.abort();
      cancelAnimationFrame(raf);
      window.clearTimeout(moveTimer);
      unsubFilters();
      unsubSel();
      unsubFly();
      map.remove();
    };
  }, []);

  // maplibre impose position: relative à son conteneur : il vit dans une boîte absolue.
  return (
    <div className={styles.map} data-testid="carte-3d">
      <div ref={box} className={styles.mapInner} />
    </div>
  );
}
