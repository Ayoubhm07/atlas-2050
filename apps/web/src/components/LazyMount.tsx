"use client";

/**
 * Monte un îlot client seulement quand il approche de l'écran (ou quand on le demande) :
 * l'hydratation initiale ne paie pas pour ce qui est loin sous la ligne de flottaison.
 * Le rendu serveur garde la place (min-height) : aucun décalage de mise en page.
 */
import { useEffect, useRef, useState, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  minHeight: string;
  /** monter aussi quand l'ancre est visée (#estimer) ou quand un magasin le demande */
  anchor?: string;
  when?: boolean;
}

export function LazyMount({ children, minHeight, anchor, when = false }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const [seen, setSeen] = useState(false);
  const show = seen || when;

  useEffect(() => {
    const el = box.current;
    if (!el || show) return;
    const io = new IntersectionObserver((entries) => entries.some((e) => e.isIntersecting) && setSeen(true), { rootMargin: "800px 0px" });
    io.observe(el);
    const onHash = (): void => {
      if (anchor && window.location.hash === `#${anchor}`) setSeen(true);
    };
    onHash();
    // premier geste de l'utilisateur (Tab compris) : l'îlot est monté avant que le clavier
    // ne l'atteigne, sans peser sur le chargement initial
    const onIntent = (): void => setSeen(true);
    const intents = ["keydown", "pointerdown", "touchstart", "wheel"] as const;
    window.addEventListener("hashchange", onHash);
    intents.forEach((t) => window.addEventListener(t, onIntent, { once: true, passive: true }));
    return () => {
      io.disconnect();
      window.removeEventListener("hashchange", onHash);
      intents.forEach((t) => window.removeEventListener(t, onIntent));
    };
  }, [show, anchor]);

  return (
    <div ref={box} style={show ? undefined : { minHeight }}>
      {show ? children : null}
    </div>
  );
}
