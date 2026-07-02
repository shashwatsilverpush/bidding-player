"""Single internal admin login -> JWT."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.auth.security import create_access_token, resolve_admin_hash, verify_password
from app.schemas.admin import LoginRequest, TokenResponse
from app.settings import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest) -> TokenResponse:
    settings = get_settings()
    admin_hash = resolve_admin_hash()
    if admin_hash is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No admin credentials configured (set ADMIN_PASSWORD or ADMIN_PASSWORD_HASH)",
        )
    if body.username != settings.admin_username or not verify_password(body.password, admin_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token, expires_in = create_access_token(settings.admin_username)
    return TokenResponse(access_token=token, expires_in=expires_in)
