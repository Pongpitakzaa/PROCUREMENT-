"""ทะเบียนบุคลากร / กลุ่ม LINE (ผู้ประกอบการอยู่ที่ app/api/vendors.py)."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import StringConstraints
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_field, encrypt_field
from app.core.database import get_db
from app.core.security import Perm, require
from app.models import NotificationChannel, NotificationLog, Personnel, User
from app.schemas import StrictModel
from app.services.audit_service import write_audit

router = APIRouter(prefix="/api", tags=["registry"])
DB = Annotated[Session, Depends(get_db)]


@router.get("/personnel")
def list_personnel(db: DB, _: Annotated[User, Depends(require(Perm.PROJECT_READ))],
                   department_id: int | None = None) -> list[dict]:
    """ใช้ใน dropdown เลือกกรรมการ — ไม่ส่งเลขบัตรประชาชน (data minimization)."""
    stmt = select(Personnel).where(Personnel.is_active.is_(True)).order_by(Personnel.first_name_th)
    if department_id:
        stmt = stmt.where(Personnel.department_id == department_id)
    return [{"personnel_id": p.personnel_id, "full_name_th": p.full_name_th, "position_th": p.position_th}
            for p in db.scalars(stmt)]


class LineChannelIn(StrictModel):
    name_th: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    # groupId/userId ของ LINE: ขึ้นต้น C (กลุ่ม) / U (ผู้ใช้) ตามด้วย hex 32 ตัว
    line_to: Annotated[str, StringConstraints(pattern=r"^[CU][0-9a-f]{32}$")]
    department_id: int | None = None


class LineChannelToggle(StrictModel):
    is_active: bool


@router.get("/admin/line-channels")
def list_line_channels(db: DB, _: Annotated[User, Depends(require(Perm.USER_MANAGE))]) -> list[dict]:
    """groupId แสดงแบบปิดบัง (ใช้ระบุกลุ่มได้ แต่ไม่พอจะนำไปส่งข้อความเอง)."""
    out = []
    for ch in db.scalars(select(NotificationChannel).order_by(NotificationChannel.channel_id)):
        to = decrypt_field(ch.line_to_enc, "notification_channels.line_to")
        last = db.scalar(select(func.max(NotificationLog.sent_at)).where(NotificationLog.channel_id == ch.channel_id))
        out.append({"channel_id": ch.channel_id, "name_th": ch.name_th, "line_to_masked": f"{to[0]}…{to[-4:]}",
                    "is_active": ch.is_active, "last_sent_at": last})
    return out


@router.patch("/admin/line-channels/{channel_id}")
def toggle_line_channel(channel_id: int, body: LineChannelToggle, request: Request, db: DB,
                        user: Annotated[User, Depends(require(Perm.USER_MANAGE))]) -> dict:
    ch = db.get(NotificationChannel, channel_id)
    if ch is None:
        raise HTTPException(404, "ไม่พบกลุ่ม LINE")
    ch.is_active = body.is_active
    write_audit(db, action="UPDATE", user_id=user.user_id, request=request, entity_table="notification_channels",
                entity_id=channel_id, new={"is_active": body.is_active})
    return {"channel_id": channel_id, "is_active": ch.is_active}


@router.post("/admin/line-channels", status_code=201)
def create_line_channel(body: LineChannelIn, request: Request, db: DB,
                        user: Annotated[User, Depends(require(Perm.USER_MANAGE))]) -> dict:
    ch = NotificationChannel(name_th=body.name_th, department_id=body.department_id,
                             line_to_enc=encrypt_field(body.line_to, "notification_channels.line_to"))
    db.add(ch)
    db.flush()
    write_audit(db, action="CREATE", user_id=user.user_id, request=request, entity_table="notification_channels",
                entity_id=ch.channel_id, new={"name_th": body.name_th})
    return {"channel_id": ch.channel_id}
