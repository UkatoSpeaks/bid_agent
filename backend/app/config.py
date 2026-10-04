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

    # LLM (extraction and classification only; it never prices anything).
    groq_api_key: str | None = None
    llm_model: str = "openai/gpt-oss-120b"
    llm_temperature: float = 0.2
    llm_reasoning_effort: str = "medium"
    llm_cache: bool = True
    llm_cache_dir: Path = Path(".cache/llm")

    @property
    def resolved_llm_cache_dir(self) -> Path:
        """Absolute cache directory; relative values resolve from backend/."""
        if self.llm_cache_dir.is_absolute():
            return self.llm_cache_dir
        return BACKEND_DIR / self.llm_cache_dir

    @property
    def resolved_rate_card_path(self) -> Path:
        """Absolute rate card path; relative values resolve from backend/."""
        if self.rate_card_path.is_absolute():
            return self.rate_card_path
        return BACKEND_DIR / self.rate_card_path


@lru_cache
def get_settings() -> Settings:
    return Settings()
