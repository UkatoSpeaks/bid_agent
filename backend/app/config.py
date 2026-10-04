"""Application settings, read from environment variables and .env."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Later files win: backend/.env overrides the repo-root .env.
        env_file=(BACKEND_DIR.parent / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Bid Draft Agent"
    app_env: str = "development"
    rate_card_path: Path = Path("data/rate_cards/hvac_rate_card.json")

    @property
    def resolved_rate_card_path(self) -> Path:
        """Absolute rate card path; relative values resolve from backend/."""
        if self.rate_card_path.is_absolute():
            return self.rate_card_path
        return BACKEND_DIR / self.rate_card_path


@lru_cache
def get_settings() -> Settings:
    return Settings()
