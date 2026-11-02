from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_DEV_JWT_SECRET = "dev-insecure-secret-do-not-use-in-production"
_INSECURE_DEV_DB_PASSWORD = "app_pass_dev"


class Settings(BaseSettings):
    """Application settings read from environment variables."""

    model_config = SettingsConfigDict(extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5440/recipe_macros"
    # Migrations run as the database owner; the API connects as the restricted `app_user`
    # (DATABASE_URL), so PostgreSQL Row-Level Security applies to it. If unset, migrations
    # fall back to DATABASE_URL.
    admin_database_url: str | None = None
    # Password given to the app_user role by migration 0003 (must match DATABASE_URL).
    app_db_password: str = _INSECURE_DEV_DB_PASSWORD
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

    # --- Recipe import: page fetching ---
    # The product token before "/" is also what robots.txt rules are matched against.
    fetch_user_agent: str = (
        "RecipeMacrosBot/0.1 (+https://github.com/RadoslawZimodro/recipe-macros)"
    )
    fetch_max_bytes: int = 2 * 1024 * 1024  # counted AFTER decompression (gzip bombs)
    fetch_connect_timeout_sec: float = 5.0
    fetch_read_timeout_sec: float = 10.0
    fetch_total_timeout_sec: float = 15.0  # whole import, redirects and body included
    fetch_max_redirects: int = 5
    page_cache_ttl_sec: int = 24 * 3600
    robots_cache_ttl_sec: int = 24 * 3600
    robots_error_cache_ttl_sec: int = 600  # an unreachable robots.txt is retried sooner
    import_rate_limit_per_min: int = 10  # imports that reach the network, per user

    # Login brute-force guard: at most N attempts per client IP per window (seconds).
    login_rate_limit_attempts: int = 10
    login_rate_limit_window_sec: int = 300

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @model_validator(mode="after")
    def _reject_default_secrets_over_https(self) -> "Settings":
        # Secure cookies mean a real (HTTPS) deployment: never use the public dev defaults.
        if self.cookie_secure and self.jwt_secret == _INSECURE_DEV_JWT_SECRET:
            raise ValueError("JWT_SECRET must be set when COOKIE_SECURE is true")
        if self.cookie_secure and self.app_db_password == _INSECURE_DEV_DB_PASSWORD:
            raise ValueError("APP_DB_PASSWORD must be set when COOKIE_SECURE is true")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
