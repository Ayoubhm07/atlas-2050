"use client";

/**
 * Recherche de commune (combobox ARIA 1.2) sur GET /communes de l'API locale.
 * Pas d'autocomplétion d'adresse dans le navigateur : seules nos données sont interrogées.
 */
import { useEffect, useId, useRef, useState } from "react";
import { errorMessage, searchCommunes } from "@/lib/api";
import type { CommuneHit } from "@/lib/types";

interface Props {
  label: string;
  onSelect: (hit: CommuneHit) => void;
  /** appelé dès que le texte change : une sélection précédente n'est plus valable */
  onEdit?: () => void;
  placeholder?: string;
}

export function CommuneSearch({ label, onSelect, onEdit, placeholder = "Bordeaux, Arcachon, Libourne…" }: Props) {
  const id = useId();
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<CommuneHit[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [error, setError] = useState<string | null>(null);
  const [none, setNone] = useState(false);
  const picked = useRef<string | null>(null);

  useEffect(() => {
    const text = q.trim();
    if (text.length < 2 || text === picked.current) {
      setHits([]);
      setNone(false);
      return;
    }
    const ctrl = new AbortController();
    const t = window.setTimeout(() => {
      searchCommunes(text, { signal: ctrl.signal })
        .then((h) => {
          setHits(h);
          setOpen(true);
          setActive(h.length ? 0 : -1);
          setNone(h.length === 0);
          setError(null);
        })
        .catch((err: unknown) => {
          if (!ctrl.signal.aborted) setError(errorMessage(err));
        });
    }, 180);
    return () => {
      window.clearTimeout(t);
      ctrl.abort();
    };
  }, [q]);

  const choose = (h: CommuneHit): void => {
    picked.current = h.nom_commune;
    setQ(h.nom_commune);
    setOpen(false);
    setHits([]);
    onSelect(h);
  };

  const onKey = (e: React.KeyboardEvent<HTMLInputElement>): void => {
    if (e.key === "ArrowDown" && hits.length) {
      e.preventDefault();
      setOpen(true);
      setActive((a) => (a + 1) % hits.length);
    } else if (e.key === "ArrowUp" && hits.length) {
      e.preventDefault();
      setActive((a) => (a <= 0 ? hits.length - 1 : a - 1));
    } else if (e.key === "Enter" && open && active >= 0 && hits[active]) {
      e.preventDefault();
      choose(hits[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  const listId = `${id}-liste`;
  const expanded = open && hits.length > 0;
  return (
    <div className="combo">
      <label className="field" htmlFor={`${id}-q`}>
        <span>{label}</span>
        <input
          id={`${id}-q`}
          type="text"
          role="combobox"
          autoComplete="off"
          spellCheck={false}
          aria-autocomplete="list"
          aria-expanded={expanded}
          aria-controls={listId}
          aria-activedescendant={expanded && active >= 0 ? `${id}-o${active}` : undefined}
          placeholder={placeholder}
          value={q}
          onChange={(e) => {
            picked.current = null;
            setQ(e.target.value);
            onEdit?.();
          }}
          onKeyDown={onKey}
          onBlur={() => window.setTimeout(() => setOpen(false), 150)}
          onFocus={() => hits.length && setOpen(true)}
        />
      </label>
      <ul id={listId} role="listbox" aria-label={`Communes trouvées pour ${q}`} className="combo-list" hidden={!expanded}>
        {hits.map((h, i) => (
          <li
            key={h.code_insee}
            id={`${id}-o${i}`}
            role="option"
            aria-selected={i === active}
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => choose(h)}
          >
            {h.nom_commune} <span className="note">({h.code_insee})</span>
          </li>
        ))}
      </ul>
      {none && !error && (
        <p className="note" role="status">
          Aucune commune couverte ne commence par « {q.trim()} » (Gironde seulement).
        </p>
      )}
      {error && (
        <p className="note" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
