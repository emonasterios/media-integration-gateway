"""Configuración central del gateway."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración cargada desde variables de entorno."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "Media Integration Gateway"
    debug: bool = False
    database_url: str = "sqlite+aiosqlite:///./data/gateway.db"
    host: str = "0.0.0.0"
    port: int = 8000
    allowed_origins: list[str] = Field(default_factory=lambda: ["*"])
    DATABASE_URL: str = "sqlite:///./media_gateway.db"
    CACHE_TTL_SECONDS: int = 3600


settings = Settings()
