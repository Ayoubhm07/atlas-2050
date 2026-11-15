"""Variables du modèle de prix, sans fuite temporelle.

Voisinage H3 : pour chaque vente, médiane du log(prix/m²) des `k` ventes les plus
récentes du même type dans l'anneau H3 r7 (la cellule et ses 6 voisines), parmi les
ventes de RÉFÉRENCE STRICTEMENT ANTÉRIEURES à sa date (une vente du même jour est
exclue : son prix n'était pas connu de l'acheteur). Cette médiane est lissée vers un
a priori départemental (médiane des `n_prior` dernières ventes de référence du même
type, elles aussi antérieures), avec un poids `prior_weight` en ventes fictives :
  lissé = (n · médiane_voisins + m · a_priori) / (n + m)

`reference` restreint les ventes qui peuvent servir de voisines : en validation
croisée, seules celles du pli d'entraînement ; en test temporel, seules celles de la
période d'entraînement. La cible n'entre donc jamais dans sa propre variable.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import h3
import numpy as np
import pandas as pd

NEIGHBOUR_COLUMNS: tuple[str, ...] = ("voisinage_log_prix", "voisinage_n")
_REQUIRED = ("date_mutation", "h3_r7", "type_local", "log_prix_m2")
_EPOCH = (2021, 1)  # t_mois = 0 en janvier 2021

FloatArray = np.ndarray[Any, np.dtype[np.float64]]
IntArray = np.ndarray[Any, np.dtype[np.int64]]


def add_model_features(df: pd.DataFrame) -> pd.DataFrame:
    """Transformations ligne à ligne (aucune information d'une autre vente) ; copie."""
    out = df.copy()
    dates = pd.to_datetime(out["date_mutation"])
    out["log_surface"] = np.log(out["surface_bati"].astype(float))
    out["log_terrain"] = np.log1p(out["surface_terrain"].astype(float))
    out["t_mois"] = (dates.dt.year - _EPOCH[0]) * 12 + (dates.dt.month - _EPOCH[1])
    out["log_prix_m2"] = np.log(out["prix_m2"].astype(float))
    for col in ("in_tri", "ppri"):
        if col in out.columns:
            out[col] = out[col].map({True: 1.0, False: 0.0}).astype(float)
    return out


def _ring(cell: str, ring: int, cache: dict[str, list[str]]) -> list[str]:
    if cell not in cache:
        cache[cell] = list(h3.grid_disk(cell, ring))
    return cache[cell]


def _index(
    days: IntArray, keys: list[tuple[str, str]], values: FloatArray, mask: np.ndarray[Any, Any]
) -> dict[tuple[str, str], tuple[IntArray, FloatArray]]:
    """(cellule, type) → (jours triés, log-prix dans le même ordre), ventes de référence."""
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for i in np.flatnonzero(mask):
        groups[keys[i]].append(int(i))
    out: dict[tuple[str, str], tuple[IntArray, FloatArray]] = {}
    for key, idx in groups.items():
        arr = np.asarray(idx, dtype=np.int64)
        order = np.argsort(days[arr], kind="stable")
        out[key] = (days[arr][order], values[arr][order])
    return out


def neighbourhood_log_price(
    df: pd.DataFrame,
    reference: np.ndarray[Any, Any] | None = None,
    k: int = 30,
    ring: int = 1,
    prior_weight: float = 5.0,
    n_prior: int = 500,
) -> pd.DataFrame:
    """Renvoie `voisinage_log_prix` (lissé) et `voisinage_n`, alignés sur `df.index`."""
    missing = [c for c in _REQUIRED if c not in df.columns]
    if missing:
        raise KeyError(f"Colonnes manquantes : {missing}")
    if k < 1 or n_prior < 1 or prior_weight < 0:
        raise ValueError("k et n_prior doivent être ≥ 1, prior_weight ≥ 0")
    n = len(df)
    ref = np.ones(n, dtype=bool) if reference is None else np.asarray(reference, dtype=bool)
    if ref.shape != (n,):
        raise ValueError(f"reference : {ref.shape} au lieu de ({n},)")

    days = pd.to_datetime(df["date_mutation"]).to_numpy().astype("datetime64[D]").astype(np.int64)
    values = df["log_prix_m2"].to_numpy(dtype=float)
    cells = df["h3_r7"].astype(str).tolist()
    types = df["type_local"].astype(str).tolist()
    cell_index = _index(days, list(zip(cells, types, strict=True)), values, ref)
    type_index = _index(days, [("*", t) for t in types], values, ref)

    smoothed = np.full(n, np.nan)
    counts = np.zeros(n, dtype=np.int64)
    cache: dict[str, list[str]] = {}
    for i in range(n):
        t, typ = days[i], types[i]
        prior = np.nan
        if ("*", typ) in type_index:
            tdays, tvals = type_index[("*", typ)]
            end = int(np.searchsorted(tdays, t, side="left"))
            if end:
                prior = float(np.median(tvals[max(0, end - n_prior) : end]))
        cand_days: list[IntArray] = []
        cand_vals: list[FloatArray] = []
        for cell in _ring(cells[i], ring, cache):
            hit = cell_index.get((cell, typ))
            if hit is None:
                continue
            cdays, cvals = hit
            end = int(np.searchsorted(cdays, t, side="left"))  # strictement avant
            cand_days.append(cdays[max(0, end - k) : end])
            cand_vals.append(cvals[max(0, end - k) : end])
        all_days = np.concatenate(cand_days) if cand_days else np.empty(0, np.int64)
        all_vals = np.concatenate(cand_vals) if cand_vals else np.empty(0)
        if len(all_vals) > k:
            keep = np.argsort(all_days, kind="stable")[-k:]
            all_vals = all_vals[keep]
        m = len(all_vals)
        counts[i] = m
        if m == 0:
            smoothed[i] = prior
        elif np.isnan(prior) or prior_weight == 0:
            smoothed[i] = float(np.median(all_vals))
        else:
            smoothed[i] = (m * float(np.median(all_vals)) + prior_weight * prior) / (
                m + prior_weight
            )
    return pd.DataFrame({"voisinage_log_prix": smoothed, "voisinage_n": counts}, index=df.index)
