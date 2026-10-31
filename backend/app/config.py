from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings read from environment variables."""

    model_config = SettingsConfigDict(extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5440/recipe_macros"
    redis_url: str = "redis://localhost:6379/0"
    anthropic_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
