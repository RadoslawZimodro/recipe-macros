"""Authentication endpoints: register, login, refresh (rotation + reuse detection), logout, me.

Tokens live in cookies:
  * access_token  - HttpOnly, path=/      (sent on every API call)
  * refresh_token - HttpOnly, path=/auth  (sent only to /auth/*, not to other endpoints)
  * csrf_token    - readable by JS, path=/ (double-submit CSRF, checked by require_csrf)

SameSite=Lax is enough here: the dev front (:5180) and API (:8010) are the same site
(host localhost), so the cookies are first-party; Lax still blocks cross-site
state-changing requests, which is the CSRF surface we care about.
"""

import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import rate_limit, security
from app.config import get_settings
from app.db import get_session
from app.dependencies import (
    ACCESS_COOKIE,
    CSRF_COOKIE,
    REFRESH_COOKIE,
    REFRESH_COOKIE_PATH,
    get_current_user,
    require_csrf,
)
from app.models import RefreshToken, User
from app.schemas.auth import GoalsIn, UserLogin, UserOut, UserRegister

router = APIRouter(prefix="/auth", tags=["auth"])

# Same wording for a missing account and a wrong password, so login does not reveal
# which of the two failed (user-enumeration defence).
_INVALID_CREDENTIALS = "Invalid email or password."

# Verified against when the account does not exist, keeping login timing roughly constant
# whether or not the email is known.
_DUMMY_HASH = security.hash_password(secrets.token_urlsafe(16))


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


# --- Cookie helpers ---
def _cookie_kwargs() -> dict:
    settings = get_settings()
    return {"secure": settings.cookie_secure, "samesite": settings.cookie_samesite}


def _set_session_cookies(response: Response, access: str, refresh: str) -> None:
    """Set access + refresh cookies and a fresh CSRF cookie."""
    settings = get_settings()
    refresh_max_age = settings.jwt_refresh_ttl_hours * 3600
    response.set_cookie(
        ACCESS_COOKIE,
        access,
        max_age=settings.jwt_access_ttl_min * 60,
        httponly=True,
        path="/",
        **_cookie_kwargs(),
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh,
        max_age=refresh_max_age,
        httponly=True,
        path=REFRESH_COOKIE_PATH,
        **_cookie_kwargs(),
    )
    # Not HttpOnly: the frontend reads it and echoes it in the X-CSRF-Token header.
    response.set_cookie(
        CSRF_COOKIE,
        secrets.token_urlsafe(32),
        max_age=refresh_max_age,
        httponly=False,
        path="/",
        **_cookie_kwargs(),
    )


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/", **_cookie_kwargs())
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH, **_cookie_kwargs())
    response.delete_cookie(CSRF_COOKIE, path="/", **_cookie_kwargs())


def _issue_session(session: Session, response: Response, user: User) -> None:
    """Store a fresh refresh-token row and set the access, refresh and CSRF cookies."""
    raw_refresh = security.generate_refresh_token()
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=security.hash_token(raw_refresh),
            expires_at=security.refresh_expiry(),
        )
    )
    session.commit()
    _set_session_cookies(response, security.create_access_token(user.id), raw_refresh)


# --- Endpoints ---
@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(
    payload: UserRegister, response: Response, session: Session = Depends(get_session)
) -> User:
    """Create an account and start a session right away (no email confirmation)."""
    user = User(email=payload.email, password_hash=security.hash_password(payload.password))
    session.add(user)
    try:
        # Flush surfaces a duplicate-email conflict. Relying on the UNIQUE constraint (not a
        # prior SELECT) keeps this correct under concurrent registrations.
        session.flush()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        ) from None

    _issue_session(session, response, user)  # commits the user too
    return user


@router.post("/login", response_model=UserOut)
def login(
    payload: UserLogin,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> User:
    """Verify credentials and start a session (access + refresh + csrf cookies)."""
    # Throttle brute force by client IP before doing any (expensive) hash verification.
    client_ip = request.client.host if request.client else "unknown"
    rate_limit.check_and_increment(client_ip)

    user = session.scalar(select(User).where(User.email == payload.email))
    # Always run a verification, so timing doesn't depend on whether the account exists.
    password_ok = security.verify_password(
        payload.password, user.password_hash if user else _DUMMY_HASH
    )
    if user is None or not password_ok or not user.is_active:
        raise _unauthorized(_INVALID_CREDENTIALS)

    rate_limit.reset(client_ip)  # a genuine login clears earlier failed attempts
    _issue_session(session, response, user)
    return user


@router.post("/refresh", response_model=UserOut)
def refresh(request: Request, response: Response, session: Session = Depends(get_session)) -> User:
    """Rotate the refresh token and mint a new access token.

    Reuse detection: presenting a refresh token that is already revoked means it was
    replayed after rotation (stolen), so every active token of that user is revoked and
    the caller must log in again.
    """
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise _unauthorized("Missing refresh token")

    # Lock the row so concurrent refreshes with the same token serialize: the second one
    # sees the (now revoked) token and trips reuse detection instead of both rotating.
    row = session.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == security.hash_token(raw))
        .with_for_update()
    )
    if row is None:
        _clear_session_cookies(response)
        raise _unauthorized("Invalid refresh token")

    if row.revoked_at is not None:
        session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == row.user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=_utcnow())
        )
        session.commit()
        _clear_session_cookies(response)
        raise _unauthorized("Refresh token reuse detected, please log in again")

    if row.expires_at < _utcnow():
        _clear_session_cookies(response)
        raise _unauthorized("Refresh token expired")

    user = session.get(User, row.user_id)
    if user is None or not user.is_active:
        _clear_session_cookies(response)
        raise _unauthorized(_INVALID_CREDENTIALS)

    # Rotate: mint a successor, then revoke the old token and link it to the new one.
    raw_new = security.generate_refresh_token()
    new_row = RefreshToken(
        user_id=user.id,
        token_hash=security.hash_token(raw_new),
        expires_at=security.refresh_expiry(),
    )
    session.add(new_row)
    session.flush()  # assigns new_row.id for the rotation link
    row.revoked_at = _utcnow()
    row.replaced_by_id = new_row.id
    session.commit()

    _set_session_cookies(response, security.create_access_token(user.id), raw_new)
    return user


@router.post("/logout")
def logout(
    request: Request, response: Response, session: Session = Depends(get_session)
) -> dict[str, str]:
    """Revoke the current refresh token (if any) and clear all session cookies."""
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.token_hash == security.hash_token(raw),
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=_utcnow())
        )
        session.commit()
    _clear_session_cookies(response)
    return {"status": "ok"}


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)) -> User:
    """Return the currently authenticated account."""
    return current_user


@router.patch("/me/goals", response_model=UserOut, dependencies=[Depends(require_csrf)])
def set_goals(
    goals: GoalsIn,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> User:
    """Set or clear the daily kcal / protein targets used by the food log."""
    for field, value in goals.model_dump(exclude_unset=True).items():
        setattr(current_user, field, value)
    session.commit()
    return current_user
