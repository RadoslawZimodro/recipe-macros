"""End-to-end auth tests: FastAPI TestClient against a real, migrated PostgreSQL database."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import APIRouter, Depends
from sqlalchemy import select, text

from app import security
from app.config import get_settings
from app.dependencies import get_current_user, require_csrf
from app.main import app
from app.models import RefreshToken, User

PASSWORD = "correcthorse7"


def register(client, email="u@example.com", password=PASSWORD):
    return client.post("/auth/register", json={"email": email, "password": password})


def login(client, email="u@example.com", password=PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


def csrf_header(client):
    return {"X-CSRF-Token": client.cookies.get("csrf_token") or ""}


# A minimal state-changing endpoint behind auth + CSRF, standing in for the real ones
# that arrive in later steps (recipes, food log).
_probe = APIRouter()


@_probe.post("/_probe", dependencies=[Depends(require_csrf)])
def _probe_post(user: User = Depends(get_current_user)) -> dict[str, int]:
    return {"user_id": user.id}


app.include_router(_probe)


# --- registration ---
def test_register_creates_account_and_starts_session(client):
    response = register(client)

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "u@example.com"
    assert body["is_active"] is True
    assert {"access_token", "refresh_token", "csrf_token"} <= set(client.cookies.keys())
    assert client.get("/auth/me").json()["email"] == "u@example.com"


def test_register_stores_argon2_hash_never_the_password(client, db):
    register(client)

    stored = db.scalar(select(User.password_hash))
    assert stored.startswith("$argon2id$")
    assert PASSWORD not in stored


def test_register_duplicate_email_conflicts(client):
    register(client)

    assert register(client).status_code == 409


def test_email_is_normalized_on_register_and_login(client):
    register(client, email="  User@Example.COM ")

    assert client.get("/auth/me").json()["email"] == "user@example.com"
    client.cookies.clear()
    assert login(client, email="USER@example.com").status_code == 200


def test_register_rejects_weak_password_and_bad_email(client):
    assert register(client, password="short").status_code == 422
    assert register(client, email="not-an-email").status_code == 422


def test_database_rejects_non_lowercase_email(db):
    with pytest.raises(Exception, match="ck_users_email_lowercase"):
        db.execute(text("INSERT INTO users (email, password_hash) VALUES ('Mixed@Case.com', 'x')"))


# --- login ---
def test_login_success_sets_cookies(client):
    register(client)
    client.cookies.clear()

    response = login(client)

    assert response.status_code == 200
    assert {"access_token", "refresh_token", "csrf_token"} <= set(client.cookies.keys())


def test_login_error_is_identical_for_unknown_email_and_wrong_password(client):
    register(client)

    wrong_password = login(client, password="wrong-password-1")
    unknown_email = login(client, email="nobody@example.com")

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


def test_inactive_user_cannot_log_in_or_use_existing_session(client, db):
    register(client)
    db.execute(text("UPDATE users SET is_active = false"))
    db.commit()

    assert client.get("/auth/me").status_code == 401
    client.cookies.clear()
    assert login(client).status_code == 401


def test_login_is_rate_limited_and_success_resets_the_counter(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "login_rate_limit_attempts", 3)
    register(client)
    client.cookies.clear()

    for _ in range(2):
        assert login(client, password="wrong-password-1").status_code == 401
    assert login(client).status_code == 200  # success clears the two failures
    for _ in range(3):
        assert login(client, password="wrong-password-1").status_code == 401

    blocked = login(client, password="wrong-password-1")
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers


# --- protected endpoints ---
def test_me_requires_authentication(client):
    assert client.get("/auth/me").status_code == 401


def test_me_rejects_garbage_and_expired_tokens(client, monkeypatch):
    client.cookies.set("access_token", "garbage")
    assert client.get("/auth/me").status_code == 401

    register(client)  # user 1 exists, so a 401 below can only come from the expired token
    client.cookies.clear()
    monkeypatch.setattr(get_settings(), "jwt_access_ttl_min", -1)
    client.cookies.set("access_token", security.create_access_token(1))
    assert client.get("/auth/me").status_code == 401


def test_each_user_sees_only_their_own_identity(client):
    register(client, email="a@example.com")
    id_a = client.get("/auth/me").json()["id"]
    client.cookies.clear()
    register(client, email="b@example.com")
    id_b = client.get("/auth/me").json()["id"]

    assert id_a != id_b
    assert client.get("/auth/me").json()["email"] == "b@example.com"


def test_password_hash_never_in_responses(client):
    responses = [register(client), client.get("/auth/me"), login(client)]

    for response in responses:
        assert "password" not in response.text


# --- CSRF ---
def test_state_changing_request_requires_matching_csrf_header(client):
    register(client)

    assert client.post("/_probe").status_code == 403
    assert client.post("/_probe", headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert client.post("/_probe", headers={"X-CSRF-Token": "żółć".encode()}).status_code == 403
    ok = client.post("/_probe", headers=csrf_header(client))
    assert ok.status_code == 200
    assert ok.json()["user_id"] == client.get("/auth/me").json()["id"]


def test_probe_without_session_is_unauthorized(client):
    client.cookies.set("csrf_token", "abc")

    assert client.post("/_probe", headers={"X-CSRF-Token": "abc"}).status_code == 401


# --- refresh / logout ---
def test_refresh_rotates_the_token_and_links_the_chain(client, db):
    register(client)
    old_refresh = client.cookies.get("refresh_token", path="/auth")

    assert client.post("/auth/refresh").status_code == 200

    assert client.cookies.get("refresh_token", path="/auth") != old_refresh
    rows = db.scalars(select(RefreshToken).order_by(RefreshToken.id)).all()
    assert len(rows) == 2
    assert rows[0].revoked_at is not None
    assert rows[0].replaced_by_id == rows[1].id
    assert rows[1].revoked_at is None


def test_refresh_token_is_stored_only_as_a_hash(client, db):
    register(client)
    raw = client.cookies.get("refresh_token", path="/auth")

    stored = db.scalar(select(RefreshToken.token_hash))
    assert stored == security.hash_token(raw)
    assert raw not in stored


def test_refresh_token_cookie_is_not_sent_outside_auth_path(client):
    register(client)
    refresh_cookie = next(c for c in client.cookies.jar if c.name == "refresh_token")

    assert refresh_cookie.path == "/auth"


def test_reuse_of_a_rotated_refresh_token_revokes_the_whole_chain(client, db):
    register(client)
    stolen = client.cookies.get("refresh_token", path="/auth")
    assert client.post("/auth/refresh").status_code == 200  # legitimate rotation

    client.cookies.clear()
    client.cookies.set("refresh_token", stolen, path="/auth")  # attacker replays the old one
    replay = client.post("/auth/refresh")

    assert replay.status_code == 401
    assert db.scalars(select(RefreshToken).where(RefreshToken.revoked_at.is_(None))).all() == []


def test_refresh_without_cookie_or_with_unknown_token_is_unauthorized(client):
    assert client.post("/auth/refresh").status_code == 401
    client.cookies.set("refresh_token", "unknown", path="/auth")
    unknown = client.post("/auth/refresh")
    assert unknown.status_code == 401
    assert unknown.json()["detail"] == "Invalid refresh token"  # the cookie was actually sent


def test_expired_refresh_token_is_rejected(client, db):
    register(client)
    db.execute(
        text("UPDATE refresh_tokens SET expires_at = :t"),
        {"t": datetime.now(UTC) - timedelta(minutes=1)},
    )
    db.commit()

    assert client.post("/auth/refresh").status_code == 401


def test_logout_revokes_refresh_token_and_clears_cookies(client, db):
    register(client)
    raw = client.cookies.get("refresh_token", path="/auth")

    assert client.post("/auth/logout").status_code == 200

    assert client.cookies.get("access_token") is None
    assert db.scalar(select(RefreshToken.revoked_at)) is not None
    client.cookies.clear()
    client.cookies.set("refresh_token", raw, path="/auth")
    assert client.post("/auth/refresh").status_code == 401
