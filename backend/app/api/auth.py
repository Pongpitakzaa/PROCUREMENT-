from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import CurrentUser, create_access_token, permissions_of, verify_password
from app.models import User
from app.schemas import LoginIn, TokenOut
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


@router.get("/me")
def me(user: CurrentUser) -> dict:
    return {
        "user_id": user.user_id,
        "username": user.username,
        "full_name_th": user.personnel.full_name_th,
        "roles": sorted(user.role_codes),
        "permissions": sorted(permissions_of(user.role_codes)),
    }
