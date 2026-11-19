"""Authentication and authorization utilities for Admin API."""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Annotated
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.enums import AdminRole, ROLE_RANK
from app.models import AdminUser, utcnow

bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    salt = get_settings().secret_key[:16]
    return hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()


def verify_password(plain: str, hashed: str) -> bool:
    return hmac.compare_digest(hash_password(plain), hashed)


def generate_token(username: str, role: str, token_version: int) -> str:
    s = get_settings()
    exp = int(time.time()) + (s.admin_token_ttl_minutes * 60)
    payload = f"{username}|{role}|{token_version}|{exp}"
    sig = hmac.new(s.secret_key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}|{sig}"


def decode_token(token: str) -> tuple[str, str, int]:
    s = get_settings()
    parts = token.split("|")
    if len(parts) != 5:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token format")
    username, role, ver_str, exp_str, sig = parts
    payload = f"{username}|{role}|{ver_str}|{exp_str}"
    expected_sig = hmac.new(s.secret_key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(sig, expected_sig):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token signature")
    if int(exp_str) < time.time():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")

    return username, role, int(ver_str)


def get_current_admin(
    creds: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_scheme)],
    session: Annotated[Session, Depends(get_db)]
) -> AdminUser:
    if not creds:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authorization header")
    username, role, token_ver = decode_token(creds.credentials)
    stmt = select(AdminUser).where(AdminUser.username == username, AdminUser.active.is_(True))
    admin = session.scalars(stmt).first()
    if not admin:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin user not found or inactive")
    if admin.token_version != token_ver:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked")
    return admin


def require_role(min_role: AdminRole):
    def role_checker(admin: Annotated[AdminUser, Depends(get_current_admin)]) -> AdminUser:
        user_rank = ROLE_RANK.get(admin.role, 0)
        req_rank = ROLE_RANK.get(min_role, 0)
        if user_rank < req_rank:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient admin privileges")
        return admin
    return role_checker


def seed_admin_user(session: Session, username: str = "admin", password: str = "BecciAdmin2026!", role: str = AdminRole.ADMIN):
    stmt = select(AdminUser).where(AdminUser.username == username)
    admin = session.scalars(stmt).first()
    if not admin:
        admin = AdminUser(
            username=username,
            password_hash=hash_password(password),
            role=role,
            active=True,
            created_at=utcnow(),
        )
        session.add(admin)
        session.commit()
    return admin
