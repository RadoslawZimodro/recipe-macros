import jwt
import pytest

from app import security
from app.config import Settings, get_settings


def test_password_hash_roundtrip_and_is_argon2id():
    hashed = security.hash_password("correcthorse7")

    assert hashed.startswith("$argon2id$")
    assert security.verify_password("correcthorse7", hashed)
    assert not security.verify_password("wrong-password", hashed)


def test_hashing_same_password_twice_gives_different_hashes():
    assert security.hash_password("correcthorse7") != security.hash_password("correcthorse7")


def test_verify_password_treats_malformed_hash_as_mismatch():
    assert security.verify_password("anything", "not-a-hash") is False


@pytest.mark.parametrize(
    ("password", "is_valid"),
    [("short", False), ("        ", False), ("x" * 129, False), ("x" * 8, True), ("x" * 128, True)],
)
def test_password_strength_rules(password, is_valid):
    assert (security.validate_password_strength(password) is None) is is_valid


def test_access_token_roundtrip():
    payload = security.decode_access_token(security.create_access_token(42))

    assert payload["sub"] == "42"
    assert payload["typ"] == "access"


def test_decode_rejects_expired_token(monkeypatch):
    monkeypatch.setattr(get_settings(), "jwt_access_ttl_min", -1)

    with pytest.raises(jwt.ExpiredSignatureError):
        security.decode_access_token(security.create_access_token(1))


def test_decode_rejects_token_signed_with_another_secret():
    forged = jwt.encode(
        {"sub": "1", "typ": "access", "exp": 9999999999}, "o" * 32, algorithm="HS256"
    )

    with pytest.raises(jwt.InvalidSignatureError):
        security.decode_access_token(forged)


def test_decode_rejects_token_of_another_type():
    settings = get_settings()
    wrong_type = jwt.encode(
        {"sub": "1", "typ": "refresh", "exp": 9999999999},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(jwt.InvalidTokenError):
        security.decode_access_token(wrong_type)


def test_refresh_tokens_are_random_and_hashed_deterministically():
    first, second = security.generate_refresh_token(), security.generate_refresh_token()

    assert first != second
    assert security.hash_token(first) == security.hash_token(first)
    assert len(security.hash_token(first)) == 64


def test_default_jwt_secret_is_rejected_when_cookies_are_secure():
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(cookie_secure=True, app_db_password="a-real-password")

    with pytest.raises(ValueError, match="APP_DB_PASSWORD"):
        Settings(cookie_secure=True, jwt_secret="a-real-secret")

    secure = Settings(cookie_secure=True, jwt_secret="a-real-secret", app_db_password="a-real-pw")
    assert secure.cookie_secure is True
