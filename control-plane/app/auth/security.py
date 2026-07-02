"""Password hashing + JWT issue/verify.

Run ``python -m app.auth.security "my-password"`` to print a bcrypt hash suitable
for the ADMIN_PASSWORD_HASH env var.
"""

from __future__ import annotations

import sys
from datetime import timedelta

import jwt
from passlib.context import CryptContext

from app.db import utcnow
from app.settings import get_settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(password, hashed)
    except ValueError:
        return False


def resolve_admin_hash() -> str | None:
    """The effective admin password hash: prefer ADMIN_PASSWORD_HASH, else hash the
    plaintext ADMIN_PASSWORD (dev convenience)."""
    s = get_settings()
    if s.admin_password_hash:
        return s.admin_password_hash
    if s.admin_password:
        return hash_password(s.admin_password)
    return None


def create_access_token(subject: str) -> tuple[str, int]:
    s = get_settings()
    expire_minutes = s.access_token_expire_minutes
    exp = utcnow() + timedelta(minutes=expire_minutes)
    payload = {"sub": subject, "exp": exp, "iat": utcnow()}
    token = jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)
    return token, expire_minutes * 60


def decode_token(token: str) -> dict:
    s = get_settings()
    return jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm])


if __name__ == "__main__":  # pragma: no cover
    if len(sys.argv) != 2:
        print('usage: python -m app.auth.security "<password>"', file=sys.stderr)
        raise SystemExit(2)
    print(hash_password(sys.argv[1]))
