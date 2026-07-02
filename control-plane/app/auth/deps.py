"""FastAPI dependency enforcing a valid admin bearer token."""

from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.security import decode_token
from app.settings import get_settings

_bearer = HTTPBearer(auto_error=True)


def require_admin(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
) -> str:
    """Return the admin subject if the token is valid, else 401."""
    try:
        payload = decode_token(creds.credentials)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    sub = payload.get("sub")
    if sub != get_settings().admin_username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authorized",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return sub


AdminDep = Depends(require_admin)
