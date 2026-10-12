"""จัดการผู้ใช้งาน (เฉพาะผู้มีสิทธิ์ user:manage) + เปลี่ยนรหัสผ่านของตนเอง.

หลักการ:
- รหัสผ่านเริ่มต้น/รีเซ็ต สุ่มโดยระบบและแสดงครั้งเดียว — ผู้ดูแลไม่ตั้งรหัสผ่านให้ผู้อื่นเอง
- รีเซ็ตรหัสผ่าน/ระงับบัญชี มีผลทันที (token เดิมใช้ไม่ได้ เพราะผูกกับ password_changed_at และ is_active)
- กันระบบไม่มีผู้ดูแล: ห้ามระงับ/ถอดบทบาท ADMIN ของตนเอง และต้องเหลือ ADMIN ที่ใช้งานอยู่อย่างน้อย 1 คน
- แบ่งแยกหน้าที่ระดับบทบาท (role_combination_problems)
"""
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import blind_index, encrypt_field
from app.core.database import get_db
from app.core.security import (ROLE_PERMISSIONS, CurrentUser, Perm, create_access_token, generate_temp_password,
                               hash_password, password_problems, require, role_combination_problems,
                               verify_password)
from app.models import Department, Personnel, Role, User
from app.schemas import ChangePasswordIn, TokenOut, UserCreate, UserUpdate
from app.services.audit_service import write_audit

router = APIRouter(tags=["users"])
DB = Annotated[Session, Depends(get_db)]
Manager = Annotated[User, Depends(require(Perm.USER_MANAGE))]

ROLE_DESC_TH = {
    "PROCUREMENT_OFFICER": "จัดทำโครงการ บันทึกขั้นตอน สร้างเอกสาร ลงทะเบียนผู้ประกอบการ",
    "HEAD_OF_PROCUREMENT": "เหมือนเจ้าหน้าที่ + อนุมัติขั้นตอน รับรองแบบฟอร์ม บันทึกผู้ทิ้งงาน",
    "EXECUTIVE": "อนุมัติขั้นตอน ดูโครงการและ Dashboard",
    "AUDITOR": "อ่านอย่างเดียว + ตรวจ Audit Log",
    "ADMIN": "ดูแลระบบ: ผู้ใช้ สำรอง/กู้คืน แบบฟอร์ม กลุ่ม LINE (ไม่ทำรายการพัสดุ)",
}


def _user_out(u: User) -> dict:
    now = datetime.now(UTC)
    return {
        "user_id": u.user_id, "username": u.username, "full_name_th": u.personnel.full_name_th,
        "position_th": u.personnel.position_th, "personnel_id": u.personnel_id,
        "roles": sorted(u.role_codes), "is_active": u.is_active,
        "is_locked": bool(u.locked_until and u.locked_until > now), "locked_until": u.locked_until,
        "failed_login_count": u.failed_login_count, "last_login_at": u.last_login_at,
        "password_changed_at": u.password_changed_at,
    }


def _get_user(db: Session, user_id: int) -> User:
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "ไม่พบผู้ใช้")
    return u


def _fail(problems: list[str]) -> HTTPException:
    return HTTPException(422, " · ".join(problems))


def _active_admin_count(db: Session, excluding: int | None = None) -> int:
    admins = [u for u in db.scalars(select(User).where(User.is_active.is_(True))) if "ADMIN" in u.role_codes]
    return sum(1 for u in admins if u.user_id != excluding)


def _set_roles(db: Session, user: User, codes: set[str]) -> None:
    user.roles = list(db.scalars(select(Role).where(Role.code.in_(codes))))


# ---------------------------------------------------------------------------
@router.get("/api/admin/roles")
def list_roles(_: Manager) -> list[dict]:
    return [{"code": code, "description_th": ROLE_DESC_TH[code], "permissions": sorted(ROLE_PERMISSIONS[code])}
            for code in ROLE_DESC_TH]


@router.get("/api/admin/users")
def list_users(db: DB, _: Manager) -> list[dict]:
    return [_user_out(u) for u in db.scalars(select(User).order_by(User.username))]


@router.get("/api/admin/personnel-without-account")
def personnel_without_account(db: DB, _: Manager) -> list[dict]:
    """บุคลากรที่ยังไม่มีบัญชี — ไม่ส่งเลขบัตรประชาชน (data minimization)."""
    has_account = select(User.personnel_id)
    rows = db.scalars(select(Personnel).where(Personnel.is_active.is_(True),
                                              Personnel.personnel_id.not_in(has_account))
                      .order_by(Personnel.first_name_th))
    return [{"personnel_id": p.personnel_id, "full_name_th": p.full_name_th, "position_th": p.position_th}
            for p in rows]


@router.post("/api/admin/users", status_code=201)
def create_user(body: UserCreate, request: Request, db: DB, admin: Manager) -> dict:
    roles = set(body.roles)
    if problems := role_combination_problems(roles):
        raise _fail(problems)
    if db.scalar(select(User.user_id).where(User.username == body.username)):
        raise HTTPException(409, "ชื่อผู้ใช้นี้มีอยู่แล้ว")

    if body.personnel is not None:
        p = body.personnel
        if db.get(Department, p.department_id) is None:
            raise HTTPException(422, "ไม่พบหน่วยงาน")
        if db.scalar(select(Personnel.personnel_id).where(Personnel.citizen_id_hmac == blind_index(p.citizen_id))):
            raise HTTPException(409, "บุคลากรที่มีเลขประจำตัวประชาชนนี้มีอยู่แล้ว — เลือกจากรายชื่อบุคลากรเดิม")
        person = Personnel(department_id=p.department_id, title_th=p.title_th, first_name_th=p.first_name_th,
                           last_name_th=p.last_name_th, position_th=p.position_th, employment_type=p.employment_type,
                           citizen_id_enc=encrypt_field(p.citizen_id, "personnel.citizen_id"),
                           citizen_id_hmac=blind_index(p.citizen_id))
        db.add(person)
        db.flush()
        write_audit(db, action="CREATE", user_id=admin.user_id, request=request, entity_table="personnel",
                    entity_id=person.personnel_id, new=p.model_dump(exclude={"citizen_id"}))
    else:
        person = db.get(Personnel, body.personnel_id)
        if person is None or not person.is_active:
            raise HTTPException(422, "ไม่พบบุคลากร")
        if db.scalar(select(User.user_id).where(User.personnel_id == person.personnel_id)):
            raise HTTPException(409, "บุคลากรนี้มีบัญชีผู้ใช้อยู่แล้ว")

    temp = generate_temp_password()
    user = User(personnel_id=person.personnel_id, username=body.username, password_hash=hash_password(temp),
                password_changed_at=datetime.now(UTC))
    db.add(user)
    db.flush()
    _set_roles(db, user, roles)
    write_audit(db, action="CREATE", user_id=admin.user_id, request=request, entity_table="users",
                entity_id=user.user_id, new={"username": body.username, "roles": sorted(roles),
                                             "personnel_id": person.personnel_id})
    db.flush()
    db.refresh(user)
    return {"user": _user_out(user), "temporary_password": temp}


@router.patch("/api/admin/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, request: Request, db: DB, admin: Manager) -> dict:
    u = _get_user(db, user_id)
    old = {"roles": sorted(u.role_codes), "is_active": u.is_active}
    new_roles = set(body.roles) if body.roles is not None else u.role_codes
    new_active = body.is_active if body.is_active is not None else u.is_active

    problems = role_combination_problems(new_roles)
    if u.user_id == admin.user_id and (not new_active or "ADMIN" not in new_roles):
        problems.append("ห้ามระงับบัญชีหรือถอดบทบาทผู้ดูแลระบบของตนเอง")
    if "ADMIN" in u.role_codes and u.is_active and ("ADMIN" not in new_roles or not new_active) \
            and _active_admin_count(db, excluding=u.user_id) == 0:
        problems.append("ต้องมีผู้ดูแลระบบที่ใช้งานอยู่อย่างน้อย 1 คน")
    if problems:
        raise _fail(problems)

    if body.roles is not None:
        _set_roles(db, u, new_roles)
    u.is_active = new_active
    write_audit(db, action="UPDATE", user_id=admin.user_id, request=request, entity_table="users",
                entity_id=user_id, old=old, new={"roles": sorted(new_roles), "is_active": new_active})
    db.flush()
    return _user_out(u)


@router.post("/api/admin/users/{user_id}/unlock")
def unlock_user(user_id: int, request: Request, db: DB, admin: Manager) -> dict:
    u = _get_user(db, user_id)
    u.failed_login_count, u.locked_until = 0, None
    write_audit(db, action="UNLOCK", user_id=admin.user_id, request=request, entity_table="users", entity_id=user_id)
    return _user_out(u)


@router.post("/api/admin/users/{user_id}/reset-password")
def reset_password(user_id: int, request: Request, db: DB, admin: Manager) -> dict:
    u = _get_user(db, user_id)
    if u.user_id == admin.user_id:
        raise HTTPException(422, "เปลี่ยนรหัสผ่านของตนเองที่เมนู “เปลี่ยนรหัสผ่าน”")
    temp = generate_temp_password()
    u.password_hash = hash_password(temp)
    u.password_changed_at = datetime.now(UTC)          # token เดิมของผู้ใช้นี้ใช้ไม่ได้ทันที
    u.failed_login_count, u.locked_until = 0, None
    write_audit(db, action="PASSWORD_RESET", user_id=admin.user_id, request=request, entity_table="users",
                entity_id=user_id)
    return {"user": _user_out(u), "temporary_password": temp}


# ---------------------------------------------------------------------------
@router.post("/api/auth/change-password", response_model=TokenOut)
def change_password(body: ChangePasswordIn, request: Request, db: DB, user: CurrentUser) -> TokenOut:
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(403, "รหัสผ่านปัจจุบันไม่ถูกต้อง")
    problems = password_problems(body.new_password, user.username)
    if body.new_password == body.current_password:
        problems.append("รหัสผ่านใหม่ต้องไม่ซ้ำรหัสผ่านเดิม")
    if problems:
        raise _fail(problems)
    user.password_hash = hash_password(body.new_password)
    user.password_changed_at = datetime.now(UTC)
    write_audit(db, action="PASSWORD_CHANGE", user_id=user.user_id, request=request, entity_table="users",
                entity_id=user.user_id)
    # token เดิมหมดอายุทันที (ผูกกับ password_changed_at) → ออก token ใหม่ให้ใช้งานต่อได้
    return TokenOut(access_token=create_access_token(user), expires_in=get_settings().access_token_minutes * 60)
