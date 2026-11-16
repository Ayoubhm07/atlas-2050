"""Configuration lue depuis l'environnement, validée au démarrage."""

import re
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# src/atlas_api/config.py → racine du dépôt (apps/api/src/atlas_api → 4 niveaux)
_REPO_ROOT = Path(__file__).resolve().parents[4]
_RATE = re.compile(r"^\s*(\d+)\s*/\s*(second|minute|hour)\s*$")
_PERIODS = {"second": 1.0, "minute": 60.0, "hour": 3600.0}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(_REPO_ROOT / ".env"), ".env"), extra="ignore", frozen=True
    )

    api_cors_origins: str = Field(default="http://localhost:3000")
    atlas_departements: str = Field(default="33,13,59")

    # PostGIS (lecture seule du schéma gold)
    postgres_host: str = "127.0.0.1"  # pas localhost : ::1 essayé d'abord, port lié en IPv4
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_user: str = "atlas"
    postgres_password: SecretStr = SecretStr("")
    postgres_db: str = "atlas"
    api_db_pool_min: int = Field(default=1, ge=1, le=50)
    api_db_pool_max: int = Field(default=10, ge=1, le=100)
    api_db_timeout_s: float = Field(default=5.0, gt=0, le=60)
    api_statement_timeout_ms: int = Field(default=3000, ge=100, le=60_000)

    # Protection
    api_rate_limit: str = "60/minute"
    # IP du client derrière un proxy : uvicorn --proxy-headers + FORWARDED_ALLOW_IPS
    # (variable lue par uvicorn, pas ici ; docs/api/README.md)
    api_cache_max_age_s: int = Field(default=3600, ge=0, le=86_400)

    # Carte H3
    api_hex_max_rows: int = Field(default=5000, ge=1, le=50_000)
    api_hex_max_area_r7: float = Field(default=4.0, gt=0)  # degrés carrés
    api_hex_max_area_r9: float = Field(default=0.25, gt=0)

    # Modèle de prix (sprint 3)
    atlas_ml_dir: Path = _REPO_ROOT / "ml"

    # Géocodage BAN (api-adresse.data.gouv.fr)
    api_ban_url: str = "https://api-adresse.data.gouv.fr/search/"
    api_ban_timeout_s: float = Field(default=2.0, gt=0, le=3)  # par tentative
    api_ban_deadline_s: float = Field(default=3.0, gt=0, le=3)  # toutes tentatives comprises
    api_ban_cache_size: int = Field(default=256, ge=0, le=10_000)
    api_ban_retries: int = Field(default=2, ge=0, le=5)
    api_ban_min_score: float = Field(default=0.5, ge=0, le=1)

    @field_validator("atlas_departements")
    @classmethod
    def _valid_departements(cls, value: str) -> str:
        codes = [c.strip() for c in value.split(",") if c.strip()]
        if not codes:
            raise ValueError("ATLAS_DEPARTEMENTS ne peut pas être vide")
        for code in codes:
            if not (code.isdigit() and len(code) in (2, 3)) and code not in ("2A", "2B"):
                raise ValueError(f"Code département invalide : {code!r}")
        return ",".join(codes)

    @field_validator("api_rate_limit")
    @classmethod
    def _valid_rate(cls, value: str) -> str:
        m = _RATE.match(value)
        if not m or int(m.group(1)) < 1:
            raise ValueError("API_RATE_LIMIT attendu sous la forme N/second|minute|hour, N ≥ 1")
        return value

    @field_validator("api_ban_url")
    @classmethod
    def _https_only(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("API_BAN_URL doit être en https")
        return value

    @property
    def cors_origins(self) -> tuple[str, ...]:
        return tuple(o.strip() for o in self.api_cors_origins.split(",") if o.strip())

    @property
    def departements(self) -> tuple[str, ...]:
        return tuple(self.atlas_departements.split(","))

    @property
    def rate_limit(self) -> tuple[int, float]:
        """(capacité du seau, secondes pour le remplir)."""
        m = _RATE.match(self.api_rate_limit)
        assert m is not None  # validé ci-dessus
        return int(m.group(1)), _PERIODS[m.group(2)]

    def conninfo(self) -> str:
        """Chaîne de connexion psycopg (contient le mot de passe : jamais journalisée)."""
        from psycopg.conninfo import make_conninfo

        return make_conninfo(
            host=self.postgres_host,
            port=self.postgres_port,
            user=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            dbname=self.postgres_db,
            connect_timeout=int(self.api_db_timeout_s) or 1,
            application_name="atlas-api",
            options=f"-c statement_timeout={self.api_statement_timeout_ms}"
            " -c default_transaction_read_only=on",
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
