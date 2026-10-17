from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import CurrentUser, create_access_token, permissions_of, verify_password
from app.models import User
from app.rules.validators import clean_text
from app.schemas import LoginIn, ProfileUpdate, TokenOut
from app.services.audit_service import write_audit

router = APIRouter(prefix="/api/auth", tags=["auth"])
DB = Annotated[Session, Depends(get_db)]


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: DB) -> TokenOut:
    s = get_settings()
    # FOR UPDATE: กัน race condition ของตัวนับ login ผิดเมื่อยิงพร้อมกันหลาย request
    user = db.scalar(select(User).where(User.username == body.username).with_for_update(of=User))
    now = datetime.now(UTC)

    if user and user.locked_until and user.locked_until > now:
        write_audit(db, action="LOGIN_LOCKED", user_id=user.user_id, request=request)
        db.commit()
        raise HTTPException(status.HTTP_423_LOCKED, "บัญชีถูกระงับชั่วคราวจากการเข้าสู่ระบบผิดหลายครั้ง")

    if not verify_password(user.password_hash if user else None, body.password) or not user or not user.is_active:
        if user:
            user.failed_login_count += 1
            if user.failed_login_count >= s.max_failed_logins:
                user.locked_until = now + timedelta(minutes=s.lockout_minutes)
                user.failed_login_count = 0
        write_audit(db, action="LOGIN_FAILED", user_id=user.user_id if user else None, request=request,
                    new={"username": body.username})
        db.commit()   # บันทึกตัวนับแม้จะตอบ 401
        # ข้อความเดียวกันทุกกรณี — ไม่บอกว่า username มีอยู่จริงหรือไม่
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")

    user.failed_login_count, user.locked_until, user.last_login_at = 0, None, now
    write_audit(db, action="LOGIN", user_id=user.user_id, request=request)
    return TokenOut(access_token=create_access_token(user), expires_in=s.access_token_minutes * 60)


PROFILE_FIELDS = ("title_th", "first_name_th", "last_name_th", "position_th", "employment_type")


def _me_payload(user: User) -> dict:
    p = user.personnel
    return {
        "user_id": user.user_id,
        "username": user.username,
        "full_name_th": p.full_name_th,
        "roles": sorted(user.role_codes),
        "permissions": sorted(permissions_of(user.role_codes)),
        "profile": {f: getattr(p, f) for f in PROFILE_FIELDS} | {"department_name_th": p.department.name_th},
    }


@router.get("/me")
def me(user: CurrentUser) -> dict:
    return _me_payload(user)


@router.patch("/me/profile")
def update_profile(body: ProfileUpdate, request: Request, db: DB, user: CurrentUser) -> dict:
    """แก้ไขคำนำหน้า ชื่อ นามสกุล ตำแหน่ง ประเภทบุคลากรของตนเอง — บันทึก audit ค่าเก่า/ใหม่."""
    changes = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if not changes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "ไม่มีข้อมูลที่เปลี่ยน")
    p = user.personnel
    old = {k: getattr(p, k) for k in changes}
    for k, v in changes.items():
        setattr(p, k, clean_text(v) if k != "employment_type" else v)
    new = {k: getattr(p, k) for k in changes}
    if new != old:
        write_audit(db, action="UPDATE", user_id=user.user_id, request=request, entity_table="personnel",
                    entity_id=p.personnel_id, old=old, new=new | {"via": "self-profile"})
    db.commit()
    db.refresh(p)
    return _me_payload(user)
