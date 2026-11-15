"""Figures matplotlib du rapport (agrégats uniquement, aucune vente individuelle)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

RIDGE, LGB, GREY = "#8c8c8c", "#1f6f8b", "#444444"


def _save(fig: Any, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path


def mae_bars(results: Mapping[str, Mapping[str, float]], path: Path) -> Path:
    """results[protocole] = {"ridge": mae, "lgb": mae}."""
    names = list(results)
    x = np.arange(len(names))
    fig, ax = plt.subplots(figsize=(6, 3.6))
    for off, key, color, label in ((-0.2, "ridge", RIDGE, "Ridge"), (0.2, "lgb", LGB, "LightGBM")):
        vals = [results[n][key] for n in names]
        bars = ax.bar(x + off, vals, 0.4, color=color, label=label)
        ax.bar_label(bars, fmt="%.0f", fontsize=8)
    ax.set_xticks(x, names)
    ax.set_ylabel("MAE (€/m²)")
    ax.set_title("Erreur absolue moyenne, baseline vs LightGBM")
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    return _save(fig, path)


def diff_ci(cis: Mapping[str, Mapping[str, float]], path: Path) -> Path:
    """Différence de MAE (LightGBM − Ridge) et IC 95 % bootstrap par commune."""
    names = list(cis)
    fig, ax = plt.subplots(figsize=(6, 2.6))
    for i, n in enumerate(names):
        c = cis[n]
        ax.errorbar(
            c["diff"],
            i,
            xerr=[[c["diff"] - c["low"]], [c["high"] - c["diff"]]],
            fmt="o",
            color=LGB,
            capsize=4,
        )
        ax.annotate(
            f"{c['diff']:.0f} [{c['low']:.0f} ; {c['high']:.0f}]",
            (c["diff"], i),
            textcoords="offset points",
            xytext=(0, 8),
            ha="center",
            fontsize=8,
        )
    ax.axvline(0, color=GREY, lw=1, ls="--")
    ax.set_yticks(range(len(names)), names)
    ax.set_ylim(-0.6, len(names) - 0.4)
    ax.set_xlabel("MAE LightGBM − MAE Ridge (€/m²) ; < 0 : LightGBM meilleur")
    ax.spines[["top", "right"]].set_visible(False)
    return _save(fig, path)


def by_group(table: pd.DataFrame, metric: str, path: Path, title: str) -> Path:
    """table : index = groupe, colonnes ridge / lgb."""
    x = np.arange(len(table))
    fig, ax = plt.subplots(figsize=(6.5, 3.4))
    for off, key, color, label in ((-0.2, "ridge", RIDGE, "Ridge"), (0.2, "lgb", LGB, "LightGBM")):
        bars = ax.bar(x + off, table[key].to_numpy(), 0.4, color=color, label=label)
        ax.bar_label(bars, fmt="%.1f" if metric == "MAPE (%)" else "%.0f", fontsize=8)
    ax.set_xticks(x, table.index.tolist(), fontsize=8)
    ax.set_ylabel(metric)
    ax.set_title(title)
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    return _save(fig, path)


def calibration(
    pred: np.ndarray[Any, Any], obs: np.ndarray[Any, Any], path: Path, n_bins: int = 10
) -> Path:
    """Médiane observée par décile de prédiction (chaque point agrège ≥ 1 / n_bins des ventes)."""
    edges = np.quantile(pred, np.linspace(0, 1, n_bins + 1))
    idx = np.clip(np.searchsorted(edges, pred, side="right") - 1, 0, n_bins - 1)
    med_p = [float(np.median(pred[idx == b])) for b in range(n_bins)]
    med_o = [float(np.median(obs[idx == b])) for b in range(n_bins)]
    q1 = [float(np.quantile(obs[idx == b], 0.25)) for b in range(n_bins)]
    q3 = [float(np.quantile(obs[idx == b], 0.75)) for b in range(n_bins)]
    fig, ax = plt.subplots(figsize=(4.8, 4.2))
    lim = [min(med_p + q1), max(med_p + q3)]
    ax.plot(lim, lim, color=GREY, lw=1, ls="--", label="y = x")
    ax.fill_between(med_p, q1, q3, color=LGB, alpha=0.15, label="Q1-Q3 observé")
    ax.plot(med_p, med_o, "o-", color=LGB, label="médiane observée")
    ax.set_xlabel("Prix prédit, médiane du décile (€/m²)")
    ax.set_ylabel("Prix observé (€/m²)")
    ax.set_title("Calibration par décile, test 2024")
    ax.legend(frameon=False, fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    return _save(fig, path)


def hbar(values: pd.Series, path: Path, xlabel: str, title: str, signed: bool = False) -> Path:
    vals = values.iloc[::-1]
    fig, ax = plt.subplots(figsize=(6.2, 0.32 * len(vals) + 1.2))
    colors = [LGB if (v >= 0 or not signed) else "#b5523b" for v in vals]
    ax.barh(vals.index.tolist(), vals.to_numpy(), color=colors)
    if signed:
        ax.axvline(0, color=GREY, lw=1)
    ax.set_xlabel(xlabel)
    ax.set_title(title)
    ax.spines[["top", "right"]].set_visible(False)
    return _save(fig, path)


def effects_plot(effects: Sequence[Mapping[str, Any]], path: Path, title: str) -> Path:
    """Écart de prix exp(β) − 1 en %, avec IC 95 % bootstrap."""
    fig, ax = plt.subplots(figsize=(6, 0.45 * len(effects) + 1.2))
    for i, e in enumerate(effects):
        mid = 100 * (e["factor"] - 1)
        lo, hi = 100 * (e["factor_low"] - 1), 100 * (e["factor_high"] - 1)
        ax.errorbar(mid, i, xerr=[[mid - lo], [hi - mid]], fmt="o", color=LGB, capsize=4)
    ax.axvline(0, color=GREY, lw=1, ls="--")
    ax.set_yticks(range(len(effects)), [str(e["term"]) for e in effects])
    ax.set_xlabel("Écart de prix/m² à caractéristiques égales (%)")
    ax.set_title(title)
    ax.spines[["top", "right"]].set_visible(False)
    return _save(fig, path)
