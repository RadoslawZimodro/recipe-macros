from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_DEV_JWT_SECRET = "dev-insecure-secret-do-not-use-in-production"


class Settings(BaseSettings):
    """Application settings read from environment variables."""

    model_config = SettingsConfigDict(extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5440/recipe_macros"
    redis_url: str = "redis://localhost:6379/0"
    anthropic_api_key: str = ""

    # Comma-separated list of origins allowed by CORS (the Vite dev server).
    cors_origins: str = "http://localhost:5180"

    # --- Authentication (JWT in cookies) ---
    # Secret for signing HS256 tokens. The default is DEV-ONLY and insecure.
    jwt_secret: str = _INSECURE_DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_min: int = 15  # access token lifetime (minutes)
    jwt_refresh_ttl_hours: int = 6  # refresh token lifetime = longest session without a login

    # Secure=False so cookies work over plain http in local dev; set COOKIE_SECURE=true
    # behind HTTPS. SameSite=Lax is enough because the dev front (:5180) and the API
    # (:8010) share the same site (host localhost).
    cookie_secure: bool = False
    cookie_samesite: str = "lax"

    # Login brute-force guard: at most N attempts per client IP per window (seconds).
    login_rate_limit_attempts: int = 10
    login_rate_limit_window_sec: int = 300

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @model_validator(mode="after")
    def _reject_default_secret_over_https(self) -> "Settings":
        # Secure cookies mean a real (HTTPS) deployment: never sign tokens with the public default.
        if self.cookie_secure and self.jwt_secret == _INSECURE_DEV_JWT_SECRET:
            raise ValueError("JWT_SECRET must be set when COOKIE_SECURE is true")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
