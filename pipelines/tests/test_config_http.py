from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from atlas_pipelines.config import PipelineConfig
from atlas_pipelines.http import RateLimiter, download, get_json, read_manifest


def test_config_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ATLAS_DEPARTEMENTS", " 33, 2A ")
    monkeypatch.setenv("ATLAS_DVF_PERIODES", "2021-s2,2024")
    cfg = PipelineConfig.from_env()
    assert cfg.departements == ("33", "2A")
    assert cfg.dvf_periodes == ("2021-s2", "2024")
    assert cfg.bronze("dvf") == tmp_path / "bronze" / "dvf"
    assert cfg.silver("dvf") == tmp_path / "silver" / "dvf"


@pytest.mark.parametrize(
    ("deps", "periodes"),
    [((), ("2024",)), (("33'; DROP",), ("2024",)), (("33",), ("2024-s3",))],
)
def test_config_rejects_invalid(deps: tuple[str, ...], periodes: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        PipelineConfig(data_dir=Path("."), departements=deps, dvf_periodes=periodes)


def test_download_is_atomic_and_idempotent(tmp_path: Path, mock_client) -> None:  # type: ignore[no-untyped-def]
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url)
        return httpx.Response(200, content=b"abc")

    dest = tmp_path / "f.bin"
    with mock_client(handler) as client:
        m1 = download(client, "https://x/f", dest)
        m2 = download(client, "https://x/f", dest)
    assert dest.read_bytes() == b"abc"
    assert m1 == m2 == read_manifest(dest)
    assert m1.bytes == 3 and len(m1.sha256) == 64
    assert len(calls) == 1
    assert not dest.with_name(".f.bin.part").exists()


def test_download_retries_transient_errors(tmp_path: Path, mock_client) -> None:  # type: ignore[no-untyped-def]
    responses = iter([503, 429, 200])

    def handler(_req: httpx.Request) -> httpx.Response:
        code = next(responses)
        return httpx.Response(code, content=b"ok" if code == 200 else b"")

    with mock_client(handler) as client:
        assert download(client, "https://x/f", tmp_path / "f").bytes == 2


def test_download_does_not_retry_404(tmp_path: Path, mock_client) -> None:  # type: ignore[no-untyped-def]
    calls = []

    def handler(_req: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(404)

    with mock_client(handler) as client, pytest.raises(httpx.HTTPStatusError):
        download(client, "https://x/f", tmp_path / "f")
    assert len(calls) == 1


def test_download_rejects_empty_body(tmp_path: Path, mock_client) -> None:  # type: ignore[no-untyped-def]
    with mock_client(lambda _r: httpx.Response(200, content=b"")) as client:
        with pytest.raises(ValueError, match="vide"):
            download(client, "https://x/f", tmp_path / "f")
    assert not (tmp_path / "f").exists()


def test_get_json_uses_limiter(mock_client) -> None:  # type: ignore[no-untyped-def]
    waits = []

    class Spy(RateLimiter):
        def wait(self) -> None:
            waits.append(1)

    with mock_client(lambda _r: httpx.Response(200, json={"a": 1})) as client:
        assert get_json(client, "https://x", limiter=Spy(1)) == {"a": 1}
    assert waits == [1]


def test_rate_limiter_spaces_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    import atlas_pipelines.http as h

    clock = [100.0]
    slept: list[float] = []
    monkeypatch.setattr(h.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(h.time, "sleep", slept.append)
    limiter = RateLimiter(calls_per_second=2)
    limiter.wait()
    limiter.wait()
    assert slept == [pytest.approx(0.5)]
    with pytest.raises(ValueError):
        RateLimiter(0)


def test_download_revalidates_with_etag(tmp_path: Path, mock_client) -> None:  # type: ignore[no-untyped-def]
    """URL fixe (`latest/`) : requête conditionnelle, 304 → réutilise, 200 → remplace."""
    seen: list[str | None] = []
    bodies = iter([(200, b"v1"), (304, b""), (200, b"v2!")])

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.headers.get("If-None-Match"))
        code, body = next(bodies)
        return httpx.Response(code, content=body, headers={"ETag": f'"{len(body)}"'})

    dest = tmp_path / "ban.csv.gz"
    with mock_client(handler) as client:
        assert download(client, "https://x/latest", dest).bytes == 2
        assert download(client, "https://x/latest", dest).bytes == 2
        assert download(client, "https://x/latest", dest).bytes == 3
    assert seen == [None, '"2"', '"2"']
    assert dest.read_bytes() == b"v2!"


def test_download_refetches_truncated_local_file(tmp_path: Path, mock_client) -> None:  # type: ignore[no-untyped-def]
    calls = []

    def handler(_req: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, content=b"abc")

    dest = tmp_path / "f"
    with mock_client(handler) as client:
        download(client, "https://x/f", dest)
        dest.write_bytes(b"a")  # fichier local abîmé
        download(client, "https://x/f", dest)
    assert len(calls) == 2 and dest.read_bytes() == b"abc"


@pytest.mark.parametrize("code", ["97", "20", "00", "96", "977", "2C"])
def test_config_rejects_ambiguous_departements(code: str) -> None:
    with pytest.raises(ValueError):
        PipelineConfig(data_dir=Path("."), departements=(code,), dvf_periodes=())


@pytest.mark.parametrize("code", ["01", "33", "95", "2A", "971", "976"])
def test_config_accepts_real_departements(code: str) -> None:
    assert PipelineConfig(data_dir=Path("."), departements=(code,), dvf_periodes=()).departements
