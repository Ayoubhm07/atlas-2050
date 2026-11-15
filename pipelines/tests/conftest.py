from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from atlas_pipelines import http as http_mod
from atlas_pipelines.config import PipelineConfig

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def cfg(tmp_path: Path) -> PipelineConfig:
    return PipelineConfig(data_dir=tmp_path, departements=("33", "13"), dvf_periodes=("2024",))


@pytest.fixture
def mock_client() -> Callable[[Handler], httpx.Client]:
    def make(handler: Handler) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)

    return make


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retries et limiteur sans attente réelle."""
    monkeypatch.setattr(http_mod.time, "sleep", lambda _s: None)
    for fn in (http_mod.download, http_mod.get_json):
        monkeypatch.setattr(fn.retry, "sleep", lambda _s: None)  # type: ignore[attr-defined]
