"""Password hashing, strength checks and JWT / refresh-token primitives.

Pure security logic with no HTTP coupling, so it can be unit-tested and reused by the
auth router and the get_current_user dependency.

Passwords use Argon2id (argon2-cffi, library defaults): memory-hard, so it resists GPU
cracking far better than bcrypt, and it has no 72-byte input limit. Access tokens are
HS256 JWTs signed with one shared secret, which fits a first-party API that both issues
and verifies its own tokens.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.config import get_settings

_hasher = PasswordHasher()

# A hard maximum guards against huge inputs (DoS via the KDF), far above any real passphrase.
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128

ACCESS_TOKEN_TYPE = "access"


# --- Passwords ---
def hash_password(password: str) -> str:
    """Return an Argon2id hash for the given plaintext password."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Check a password against a stored hash; a malformed hash is a mismatch, not an error."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def validate_password_strength(password: str) -> str | None:
    """Return a human-readable error if the password is too weak, else None."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters long."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"Password must be at most {MAX_PASSWORD_LENGTH} characters long."
    if password.strip() == "":
        return "Password cannot consist of whitespace only."
    return None


# --- JWT access tokens ---
def _now() -> datetime:
    return datetime.now(UTC)


def create_access_token(user_id: int) -> str:
    """Sign a short-lived access JWT (sub=user_id, typ=access)."""
    settings = get_settings()
    issued = _now()
    payload = {
        "sub": str(user_id),
        "typ": ACCESS_TOKEN_TYPE,
        "iat": issued,
        "exp": issued + timedelta(minutes=settings.jwt_access_ttl_min),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """Verify signature, expiry and token type; raise a jwt.PyJWTError otherwise."""
    settings = get_settings()
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "sub"]},
    )
    if payload.get("typ") != ACCESS_TOKEN_TYPE:
        raise jwt.InvalidTokenError("unexpected token type")
    return payload


# --- Refresh tokens ---
# Opaque random strings, not JWTs: the refresh_tokens table is the single source of truth,
# so self-describing claims add nothing, and a random value is trivial to revoke and rotate.
def generate_refresh_token() -> str:
    """Return a new cryptographically random refresh-token value (the raw secret)."""
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    """sha256 hex digest stored in the DB; the raw token is never persisted."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def refresh_expiry() -> datetime:
    """Absolute expiry for a freshly issued refresh token."""
    return _now() + timedelta(hours=get_settings().jwt_refresh_ttl_hours)
