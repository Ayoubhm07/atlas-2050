"""Gold et silver synthétiques (aucune donnée réelle) pour les tests du modèle."""

from __future__ import annotations

from pathlib import Path

import h3
import numpy as np
import pandas as pd

N_COMMUNES = 16


def make_sales(n: int = 1500, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    commune = rng.integers(0, N_COMMUNES, n)
    lat = 44.6 + 0.05 * (commune // 4) + rng.normal(0, 0.01, n)
    lon = -0.8 + 0.05 * (commune % 4) + rng.normal(0, 0.01, n)
    maison = rng.random(n) < 0.55
    surface = np.where(maison, rng.integers(60, 160, n), rng.integers(18, 100, n))
    days = rng.integers(0, 3 * 365, n)
    date = pd.Timestamp("2022-01-01") + pd.to_timedelta(days, unit="D")
    loc = 0.25 * np.sin(commune) + 0.1 * (commune % 3)
    log_p = 8.1 + loc - 0.15 * np.log(surface / 70) + 0.05 * maison + rng.normal(0, 0.12, n)
    prix_m2 = np.exp(log_p)
    dpe = rng.choice(list("ABCDEFG"), n)
    dpe = np.where(rng.random(n) < 0.6, dpe, "inconnu")
    return pd.DataFrame(
        {
            "id_mutation": [f"m{i}" for i in range(n)],
            "date_mutation": date.date,
            "annee": date.year.astype("int32"),
            "code_commune": [f"33{c:03d}" for c in commune],
            "code_iris": [f"33{c:03d}0000" for c in commune],
            "type_local": np.where(maison, "Maison", "Appartement"),
            "surface_bati": surface.astype("int32"),
            "pieces": np.maximum(1, surface // 25).astype("int32"),
            "surface_terrain": np.where(maison, rng.integers(200, 2000, n), np.nan),
            "n_dependances": rng.integers(0, 2, n).astype("int32"),
            "valeur_fonciere": prix_m2 * surface,
            "prix_m2": prix_m2,
            "lon": lon,
            "lat": lat,
            "h3_r7": [h3.latlng_to_cell(a, b, 7) for a, b in zip(lat, lon, strict=True)],
            "dpe_etiquette": dpe,
        }
    )


def write_lake(root: Path, n: int = 1500) -> tuple[Path, Path]:
    gold, silver = root / "gold", root / "silver"
    (silver / "georisques").mkdir(parents=True)
    gold.mkdir(parents=True)
    sales = make_sales(n)
    sales.to_parquet(gold / "fact_transactions.parquet")
    codes = [f"33{c:03d}" for c in range(N_COMMUNES)]
    pd.DataFrame(
        {
            "code_iris": [f"{c}0000" for c in codes],
            "code_insee": codes,
            "type_iris": ["H" if i % 2 else "Z" for i in range(N_COMMUNES)],
            "revenu_median": [20000.0 + 500 * i if i % 2 else np.nan for i in range(N_COMMUNES)],
            "gini": [0.25 + 0.005 * i if i % 2 else np.nan for i in range(N_COMMUNES)],
            "rga_code_exposition": [None if i % 5 == 0 else 2 + i % 2 for i in range(N_COMMUNES)],
        }
    ).to_parquet(gold / "dim_iris.parquet")
    pd.DataFrame(
        {
            "code_insee": codes,
            "in_tri": [i % 4 == 0 for i in range(N_COMMUNES)],
            "ppri": [i % 3 == 0 for i in range(N_COMMUNES)],
        }
    ).to_parquet(gold / "fact_risques_commune.parquet")
    pd.DataFrame(
        {
            "code_insee": [codes[i % 6] for i in range(12)],
            "code_national_catnat": [f"INTE{i}" for i in range(12)],
            "date_debut_evt": pd.to_datetime([f"20{15 + i % 9}-01-01" for i in range(12)]).date,
            "date_arrete": pd.to_datetime([f"20{15 + i % 9}-06-01" for i in range(12)]).date,
        }
    ).to_parquet(silver / "georisques" / "catnat.parquet")
    return gold, silver
