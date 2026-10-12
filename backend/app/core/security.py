"""Authentication (Argon2id + JWT) และ Role-Based Access Control.

หลักการ: deny-by-default — ทุก endpoint ต้องประกาศ permission ที่ต้องใช้ผ่าน require(...)
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.models import User

_hasher = PasswordHasher()   # Argon2id, memory-hard: ต้านการเดารหัสด้วย GPU
_DUMMY_HASH = _hasher.hash("timing-equalizer")


class Perm(StrEnum):
    PROJECT_READ = "project:read"
    PROJECT_WRITE = "project:write"
    STEP_SUBMIT = "step:submit"
    STEP_APPROVE = "step:approve"
    DOCUMENT_EXPORT = "document:export"
    LINE_SEND = "line:send"
    VENDOR_WRITE = "vendor:write"
    DASHBOARD_VIEW = "dashboard:view"
    TEMPLATE_MANAGE = "template:manage"
    TEMPLATE_VERIFY = "template:verify"
    USER_MANAGE = "user:manage"
    BACKUP_RUN = "backup:run"
    RESTORE_RUN = "restore:run"
    AUDIT_READ = "audit:read"


# Role → Permission (หลักถ่วงดุล: เจ้าหน้าที่เสนอ / หัวหน้า-ผู้บริหารอนุมัติ / Admin ดูแลระบบแต่ไม่อนุมัติงานพัสดุ)
ROLE_PERMISSIONS: dict[str, frozenset[Perm]] = {
    "PROCUREMENT_OFFICER": frozenset({Perm.PROJECT_READ, Perm.PROJECT_WRITE, Perm.STEP_SUBMIT,
                                      Perm.DOCUMENT_EXPORT, Perm.LINE_SEND, Perm.VENDOR_WRITE,
                                      Perm.DASHBOARD_VIEW}),
    "HEAD_OF_PROCUREMENT": frozenset({Perm.PROJECT_READ, Perm.PROJECT_WRITE, Perm.STEP_SUBMIT,
                                      Perm.STEP_APPROVE, Perm.DOCUMENT_EXPORT, Perm.LINE_SEND,
                                      Perm.VENDOR_WRITE, Perm.DASHBOARD_VIEW, Perm.TEMPLATE_VERIFY}),
    "EXECUTIVE": frozenset({Perm.PROJECT_READ, Perm.STEP_APPROVE, Perm.DOCUMENT_EXPORT, Perm.DASHBOARD_VIEW}),
    "AUDITOR": frozenset({Perm.PROJECT_READ, Perm.DASHBOARD_VIEW, Perm.AUDIT_READ}),
    "ADMIN": frozenset({Perm.PROJECT_READ, Perm.DASHBOARD_VIEW, Perm.TEMPLATE_MANAGE, Perm.USER_MANAGE,
                        Perm.BACKUP_RUN, Perm.RESTORE_RUN, Perm.AUDIT_READ}),
}


def permissions_of(role_codes: set[str]) -> frozenset[Perm]:
    return frozenset().union(*(ROLE_PERMISSIONS.get(r, frozenset()) for r in role_codes))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """ตรวจรหัสผ่าน; กรณีไม่พบผู้ใช้ก็ยัง verify กับ dummy hash เพื่อให้เวลาตอบสนองเท่ากัน (กัน user enumeration)."""
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_access_token(user: User) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user.user_id),
        "roles": sorted(user.role_codes),
        "iat": now,
        "exp": now + timedelta(minutes=s.access_token_minutes),
        # pwd_ts: เปลี่ยนรหัสผ่านแล้ว token เก่าใช้ไม่ได้ทันที
        "pwd_ts": int(user.password_changed_at.timestamp()),
    }
    return jwt.encode(payload, s.jwt_secret.get_secret_value(), algorithm=s.jwt_algorithm)


_bearer = HTTPBearer(auto_error=False)
_UNAUTHORIZED = HTTPException(status.HTTP_401_UNAUTHORIZED, "กรุณาเข้าสู่ระบบ",
                              headers={"WWW-Authenticate": "Bearer"})


def get_current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if creds is None:
        raise _UNAUTHORIZED
    s = get_settings()
    try:
        # ระบุ algorithms ชัดเจน กันการโจมตีแบบ alg=none / algorithm confusion
        payload = jwt.decode(creds.credentials, s.jwt_secret.get_secret_value(),
                             algorithms=[s.jwt_algorithm], options={"require": ["exp", "sub", "pwd_ts"]})
    except jwt.PyJWTError:
        raise _UNAUTHORIZED from None
    user = db.scalar(select(User).where(User.user_id == int(payload["sub"])))
    if user is None or not user.is_active or int(user.password_changed_at.timestamp()) != payload["pwd_ts"]:
        raise _UNAUTHORIZED
    # สิทธิ์อ่านจาก DB ทุกครั้ง (ไม่เชื่อ roles ใน token) → ถอนสิทธิ์มีผลทันที
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require(*perms: Perm):
    """Dependency factory: ต้องมีทุก permission ที่ระบุ ไม่งั้น 403."""
    def checker(user: CurrentUser) -> User:
        missing = set(perms) - permissions_of(user.role_codes)
        if missing:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "ไม่มีสิทธิ์ดำเนินการนี้")
        return user
    return checker
