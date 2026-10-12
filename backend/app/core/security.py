"""Authentication (Argon2id + JWT) และ Role-Based Access Control.

หลักการ: deny-by-default — ทุก endpoint ต้องประกาศ permission ที่ต้องใช้ผ่าน require(...)
"""
from __future__ import annotations

import secrets
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
    VENDOR_SANCTION = "vendor:sanction"   # บันทึกผู้ทิ้งงาน — ผลทางกฎหมายสูง จึงจำกัดเฉพาะหัวหน้าเจ้าหน้าที่
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
                                      Perm.VENDOR_WRITE, Perm.VENDOR_SANCTION, Perm.DASHBOARD_VIEW,
                                      Perm.TEMPLATE_VERIFY}),
    "EXECUTIVE": frozenset({Perm.PROJECT_READ, Perm.STEP_APPROVE, Perm.DOCUMENT_EXPORT, Perm.DASHBOARD_VIEW}),
    "AUDITOR": frozenset({Perm.PROJECT_READ, Perm.DASHBOARD_VIEW, Perm.AUDIT_READ}),
    "ADMIN": frozenset({Perm.PROJECT_READ, Perm.DASHBOARD_VIEW, Perm.TEMPLATE_MANAGE, Perm.USER_MANAGE,
                        Perm.BACKUP_RUN, Perm.RESTORE_RUN, Perm.AUDIT_READ}),
}


def permissions_of(role_codes: set[str]) -> frozenset[Perm]:
    return frozenset().union(*(ROLE_PERMISSIONS.get(r, frozenset()) for r in role_codes))


# ---------------------------------------------------------------------------
# นโยบายรหัสผ่าน / บทบาท (pure functions — ใช้ทั้ง API และ test)
# ---------------------------------------------------------------------------
PASSWORD_MIN_LENGTH = 12
ROLE_CODES = ("ADMIN", "PROCUREMENT_OFFICER", "HEAD_OF_PROCUREMENT", "EXECUTIVE", "AUDITOR")
_PROCUREMENT_ROLES = {"PROCUREMENT_OFFICER", "HEAD_OF_PROCUREMENT", "EXECUTIVE"}


def password_problems(password: str, username: str = "") -> list[str]:
    """นโยบายรหัสผ่าน: ยาว ≥ 12 · มีตัวอักษรและตัวเลข · ไม่มีชื่อผู้ใช้อยู่ในรหัสผ่าน."""
    problems = []
    if len(password) < PASSWORD_MIN_LENGTH:
        problems.append(f"ต้องยาวอย่างน้อย {PASSWORD_MIN_LENGTH} ตัวอักษร")
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        problems.append("ต้องมีทั้งตัวอักษรและตัวเลข")
    if username and username.lower() in password.lower():
        problems.append("ห้ามมีชื่อผู้ใช้อยู่ในรหัสผ่าน")
    return problems


def generate_temp_password() -> str:
    """รหัสผ่านชั่วคราว 16 ตัว (สุ่มด้วย secrets) — ผู้ดูแลไม่ต้องตั้งเอง/ไม่รู้ล่วงหน้า."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"   # ตัดตัวที่สับสนง่าย (0/O, 1/l/I)
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(16))
        if not password_problems(pw):
            return pw


def role_combination_problems(roles: set[str]) -> list[str]:
    """แบ่งแยกหน้าที่ (Segregation of Duties) ระดับบทบาท."""
    problems = []
    if not roles:
        problems.append("ต้องมีอย่างน้อย 1 บทบาท")
    if unknown := roles - set(ROLE_CODES):
        problems.append(f"บทบาทไม่ถูกต้อง: {sorted(unknown)}")
    if "ADMIN" in roles and roles & _PROCUREMENT_ROLES:
        problems.append("ผู้ดูแลระบบห้ามมีบทบาทในงานพัสดุ (ผู้ดูแลข้อมูลต้องไม่ใช่ผู้ทำ/อนุมัติรายการ)")
    if "AUDITOR" in roles and len(roles) > 1:
        problems.append("ผู้ตรวจสอบภายในต้องมีบทบาทเดียว (ความเป็นอิสระของผู้ตรวจสอบ)")
    return problems


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


def require_any(*perms: Perm):
    """Dependency factory: มี permission ข้อใดข้อหนึ่งก็พอ (เช่น หน้าแบบฟอร์ม: ผู้อัปโหลด หรือ ผู้ตรวจรับรอง)."""
    def checker(user: CurrentUser) -> User:
        if not set(perms) & permissions_of(user.role_codes):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "ไม่มีสิทธิ์ดำเนินการนี้")
        return user
    return checker
