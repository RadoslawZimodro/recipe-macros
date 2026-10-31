"""Shared FastAPI auth dependencies and cookie names.

get_current_user reads the access token from an HttpOnly cookie, verifies it, loads the
account and binds the database tenant. The user id used for data isolation comes ONLY
from the verified token, never from the request body, query or path.
"""

import secrets

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app import security
from app.db import get_session, set_tenant
from app.models import User

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"
CSRF_COOKIE = "csrf_token"
# The refresh cookie is scoped to /auth so it is NOT sent on ordinary API calls, while
# still reaching /auth/refresh (rotation) and /auth/logout (revocation).
REFRESH_COOKIE_PATH = "/auth"
# Header the frontend echoes the CSRF cookie value into (double-submit pattern).
CSRF_HEADER = "X-CSRF-Token"

_UNAUTHORIZED = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


def get_current_user(request: Request, session: Session = Depends(get_session)) -> User:
    """Resolve the authenticated user from the access-token cookie, or raise 401."""
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise _UNAUTHORIZED
    try:
        payload = security.decode_access_token(token)
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, ValueError):
        raise _UNAUTHORIZED from None

    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise _UNAUTHORIZED
    # From here on every query of this request is filtered by RLS to this user's rows.
    set_tenant(session, user.id)
    return user


# Methods that don't change state need no CSRF check.
_CSRF_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def require_csrf(request: Request) -> None:
    """Double-submit CSRF guard for state-changing requests.

    The csrf_token cookie is readable by JS (not HttpOnly) and the frontend echoes it in the
    X-CSRF-Token header. A cross-site attacker can make the browser send the cookies but
    cannot read the cookie value to set the header (same-origin policy), so the two only
    match on genuine same-origin requests. Compared in constant time.
    """
    if request.method in _CSRF_SAFE_METHODS:
        return
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get(CSRF_HEADER)
    # Bytes: compare_digest raises TypeError on non-ASCII str, which would surface as a 500.
    if not cookie or not header or not secrets.compare_digest(cookie.encode(), header.encode()):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")
