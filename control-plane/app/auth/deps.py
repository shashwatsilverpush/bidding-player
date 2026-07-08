"""FastAPI dependency enforcing a valid admin bearer token."""

from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.security import decode_token
from app.services.audit import set_audit_context
from app.settings import get_settings


def _client_ip(request: Request) -> str | None:
    """Real client IP: first hop of X-Forwarded-For (trusting our own proxy), else
    the socket peer. Clients can spoof the header, so only rely on it behind a proxy
    we control."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


_bearer = HTTPBearer(auto_error=True)


async def require_admin(
    request: Request,
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
) -> str:
    """Return the admin subject if the token is valid, else 401. Also stamps the
    per-request audit context (actor + device signals) for the change log.

    Must be ``async`` so it runs in the request's event-loop context: a sync
    dependency runs in a threadpool whose ContextVar writes wouldn't reach the flush.
    """
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
    set_audit_context(
        actor=sub,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        method=request.method,
        path=request.url.path,
    )
    return sub


AdminDep = Depends(require_admin)
