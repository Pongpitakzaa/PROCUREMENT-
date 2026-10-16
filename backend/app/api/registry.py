"""ทะเบียนบุคลากร / กลุ่ม LINE (ผู้ประกอบการอยู่ที่ app/api/vendors.py)."""
from typing import Annotated

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import StringConstraints
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import blind_index, decrypt_field, encrypt_field
from app.core.database import get_db
from app.core.security import Perm, require
from app.models import NotificationChannel, NotificationLog, Personnel, User
from app.schemas import StrictModel
from app.services import delivery_service, line_service
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


class LineChannelUpdate(StrictModel):
    is_active: bool | None = None
    name_th: Annotated[str, StringConstraints(min_length=1, max_length=100)] | None = None


@router.get("/admin/line-status")
def line_status(request: Request, _: Annotated[User, Depends(require(Perm.USER_MANAGE))]) -> dict:
    """สถานะการตั้งค่า LINE สำหรับหน้าผู้ดูแล — ไม่เปิดเผยค่าลับ บอกแค่ว่าตั้งแล้วหรือยัง."""
    s = get_settings()
    base = s.public_base_url.rstrip("/") or str(request.base_url).rstrip("/")
    return {"token_configured": s.line_channel_access_token is not None,
            "secret_configured": s.line_channel_secret is not None,
            "auto_notify": s.line_auto_notify,
            "webhook_url": f"{base}/api/line/webhook"}


@router.get("/admin/delivery-reminders")
def delivery_reminder_status(db: DB, _: Annotated[User, Depends(require(Perm.USER_MANAGE))]) -> dict:
    """สถานะแจ้งเตือนครบกำหนดส่งมอบ + โครงการที่ใกล้ครบ/เลยกำหนด สำหรับหน้าผู้ดูแล."""
    s = get_settings()
    return {"enabled": s.delivery_reminder_enabled, "days": sorted(s.delivery_reminder_days, reverse=True),
            "hour": s.delivery_reminder_hour, "scheduler": s.delivery_reminder_scheduler,
            **delivery_service.last_run_info(db), "upcoming": delivery_service.upcoming(db, within_days=30)}


@router.post("/admin/delivery-reminders/run")
def delivery_reminder_run(request: Request, db: DB, user: Annotated[User, Depends(require(Perm.USER_MANAGE))]) -> dict:
    """ปุ่ม "ตรวจและส่งเดี๋ยวนี้" — ส่งเฉพาะ milestone ที่ยังไม่เคยส่ง (กันซ้ำเหมือนรอบอัตโนมัติ)."""
    result = delivery_service.run_reminders(db, force=True)
    write_audit(db, action="LINE_DELIVERY_REMINDER", user_id=user.user_id, request=request, new=result)
    db.commit()
    return result


@router.get("/line-channels")
def list_active_channels(db: DB, _: Annotated[User, Depends(require(Perm.LINE_SEND))]) -> list[dict]:
    """สำหรับปุ่ม "ส่ง LINE" ในหน้าโครงการ: เฉพาะชื่อกลุ่มที่เปิดใช้ (ไม่มี ID)."""
    rows = db.scalars(select(NotificationChannel).where(NotificationChannel.is_active.is_(True))
                      .order_by(NotificationChannel.name_th))
    return [{"channel_id": ch.channel_id, "name_th": ch.name_th} for ch in rows]


@router.get("/admin/line-channels")
def list_line_channels(db: DB, _: Annotated[User, Depends(require(Perm.USER_MANAGE))]) -> list[dict]:
    """groupId แสดงแบบปิดบัง (ใช้ระบุกลุ่มได้ แต่ไม่พอจะนำไปส่งข้อความเอง)."""
    out = []
    for ch in db.scalars(select(NotificationChannel).order_by(NotificationChannel.channel_id)):
        to = decrypt_field(ch.line_to_enc, "notification_channels.line_to")
        last = db.scalar(select(func.max(NotificationLog.sent_at)).where(NotificationLog.channel_id == ch.channel_id))
        last_log = db.scalar(select(NotificationLog).where(NotificationLog.channel_id == ch.channel_id)
                             .order_by(NotificationLog.sent_at.desc()).limit(1))
        out.append({"channel_id": ch.channel_id, "name_th": ch.name_th, "line_to_masked": f"{to[0]}…{to[-4:]}",
                    "is_active": ch.is_active, "source": ch.source, "created_at": ch.created_at,
                    "last_sent_at": last, "last_status": last_log.status if last_log else None})
    return out


@router.patch("/admin/line-channels/{channel_id}")
def update_line_channel(channel_id: int, body: LineChannelUpdate, request: Request, db: DB,
                        user: Annotated[User, Depends(require(Perm.USER_MANAGE))]) -> dict:
    """เปิด/ปิด หรือตั้งชื่อกลุ่ม (กลุ่มจาก webhook มาพร้อมชื่อชั่วคราว)."""
    ch = db.get(NotificationChannel, channel_id)
    if ch is None:
        raise HTTPException(404, "ไม่พบกลุ่ม LINE")
    changed = body.model_dump(exclude_none=True)
    if not changed:
        raise HTTPException(422, "ไม่มีข้อมูลที่จะแก้ไข")
    if body.is_active is not None:
        ch.is_active = body.is_active
    if body.name_th is not None:
        ch.name_th = body.name_th
    write_audit(db, action="UPDATE", user_id=user.user_id, request=request, entity_table="notification_channels",
                entity_id=channel_id, new=changed)
    return {"channel_id": channel_id, "is_active": ch.is_active, "name_th": ch.name_th}


@router.post("/admin/line-channels/{channel_id}/test")
def test_line_channel(channel_id: int, request: Request, db: DB,
                      user: Annotated[User, Depends(require(Perm.USER_MANAGE))]) -> dict:
    """ส่งข้อความทดสอบ — ใช้ยืนยันว่า token ถูกต้องและ bot อยู่ในกลุ่มจริง (ส่งได้แม้กลุ่มยังไม่เปิดใช้)."""
    ch = db.get(NotificationChannel, channel_id)
    if ch is None:
        raise HTTPException(404, "ไม่พบกลุ่ม LINE")
    retry_key = uuid.uuid4()
    to = decrypt_field(ch.line_to_enc, "notification_channels.line_to")
    message = line_service.build_text_message(
        f"✅ ทดสอบการแจ้งเตือนจากระบบจัดซื้อจัดจ้าง\nกลุ่ม: {ch.name_th}\nโดย: {user.personnel.full_name_th}")
    try:
        http_status, result, error = line_service.push_message(to, message, retry_key), "SENT", None
    except line_service.LineSendError as exc:
        http_status, result, error = None, "FAILED", str(exc)
    db.add(NotificationLog(channel_id=channel_id, retry_key=retry_key, status=result, http_status=http_status,
                           sent_by=user.user_id))
    write_audit(db, action="LINE_SEND", user_id=user.user_id, request=request, entity_table="notification_channels",
                entity_id=channel_id, new={"test": True, "status": result})
    if result == "FAILED":
        db.commit()
        raise HTTPException(502, error)
    return {"status": result}


@router.post("/admin/line-channels", status_code=201)
def create_line_channel(body: LineChannelIn, request: Request, db: DB,
                        user: Annotated[User, Depends(require(Perm.USER_MANAGE))]) -> dict:
    h = blind_index(body.line_to)
    if db.scalar(select(NotificationChannel.channel_id).where(NotificationChannel.line_to_hmac == h)):
        raise HTTPException(409, "กลุ่มนี้ลงทะเบียนแล้ว")
    ch = NotificationChannel(name_th=body.name_th, department_id=body.department_id, line_to_hmac=h,
                             line_to_enc=encrypt_field(body.line_to, "notification_channels.line_to"))
    db.add(ch)
    db.flush()
    write_audit(db, action="CREATE", user_id=user.user_id, request=request, entity_table="notification_channels",
                entity_id=ch.channel_id, new={"name_th": body.name_th})
    return {"channel_id": ch.channel_id}
