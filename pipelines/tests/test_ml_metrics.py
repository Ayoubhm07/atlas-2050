"""Métriques et bootstrap par grappes."""

from __future__ import annotations

import numpy as np
import pytest

from atlas_pipelines.ml.metrics import cluster_bootstrap_mae_diff, scores
from atlas_pipelines.ml.tracking import flatten, resolve_tracking_uri, sanitize


def test_scores_values() -> None:
    s = scores(np.array([100.0, 200.0, 300.0]), np.array([110.0, 180.0, 300.0]))
    assert s.mae == pytest.approx(10.0)
    assert s.mape == pytest.approx((0.1 + 0.1 + 0) / 3)
    assert s.medae == pytest.approx(10.0)
    assert s.r2 == pytest.approx(1 - 500 / 20000)
    assert s.as_dict()["n"] == 3.0


def test_scores_reject_bad_input() -> None:
    with pytest.raises(ValueError):
        scores(np.array([1.0]), np.array([1.0, 2.0]))
    with pytest.raises(ValueError):
        scores(np.array([0.0, 1.0]), np.array([1.0, 1.0]))
    assert np.isnan(scores(np.array([5.0, 5.0]), np.array([4.0, 6.0])).r2)


def test_bootstrap_detects_clear_improvement() -> None:
    rng = np.random.default_rng(1)
    y = rng.uniform(1000, 5000, 2000)
    groups = rng.integers(0, 40, 2000)
    good = y + rng.normal(0, 100, 2000)
    bad = y + rng.normal(0, 400, 2000)
    ci = cluster_bootstrap_mae_diff(y, good, bad, groups, n_boot=300)
    assert ci.low <= ci.diff <= ci.high < 0
    assert ci.significant_improvement
    assert ci.n_groups == 40
    assert ci.as_dict()["significatif"] is True
    # même modèle des deux côtés : différence nulle, non significative
    same = cluster_bootstrap_mae_diff(y, good, good, groups, n_boot=50)
    assert same.diff == 0 and not same.significant_improvement


def test_bootstrap_validates_shapes() -> None:
    y = np.ones(4) * 10
    with pytest.raises(ValueError, match="Dimensions"):
        cluster_bootstrap_mae_diff(y, y, y, np.zeros(3))
    with pytest.raises(ValueError, match="deux groupes"):
        cluster_bootstrap_mae_diff(y, y, y, np.zeros(4))


def test_tracking_helpers(tmp_path: object) -> None:
    from pathlib import Path

    base = Path(str(tmp_path))
    uri = resolve_tracking_uri("http://127.0.0.1:9/", base / "mlruns", timeout=0.2)
    assert uri.startswith("file:") and (base / "mlruns").is_dir()
    assert resolve_tracking_uri(None, base / "x").startswith("file:")
    assert resolve_tracking_uri("file:///tmp/abc", base / "y") == "file:///tmp/abc"
    assert flatten("a", {"b": {"c": 1, "d": "txt", "e": True, "f": float("nan")}}) == {
        "a.b.c": 1.0,
        "a.b.e": 1.0,
    }
    assert sanitize("spatial.lgb.par_urbain.commune à IRIS.mae") == (
        "spatial.lgb.par_urbain.commune _ IRIS.mae"
    )
