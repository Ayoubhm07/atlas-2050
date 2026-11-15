"""Configuration lue depuis l'environnement, validée au démarrage."""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    api_cors_origins: str = Field(default="http://localhost:3000")
    atlas_departements: str = Field(default="33,13,59")

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

    @property
    def cors_origins(self) -> tuple[str, ...]:
        return tuple(o.strip() for o in self.api_cors_origins.split(",") if o.strip())

    @property
    def departements(self) -> tuple[str, ...]:
        return tuple(self.atlas_departements.split(","))


@lru_cache
def get_settings() -> Settings:
    return Settings()
