"""LINE Messaging API webhook — ให้ระบบรู้จักกลุ่มเองเมื่อเชิญ bot เข้ากลุ่ม (ผู้ดูแลไม่ต้องหา groupId เอง).

ความปลอดภัย: endpoint นี้ไม่มี login (LINE เป็นผู้เรียก) จึงตรวจลายเซ็น HMAC ด้วย Channel secret ทุกคำขอ
และไม่ทำอะไรนอกจากบันทึก/ปิดกลุ่ม — ไม่ตอบข้อความ ไม่ส่งข้อมูลระบบออกไป
"""
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import blind_index, encrypt_field
from app.core.database import get_db
from app.models import NotificationChannel
from app.services import line_service
from app.services.audit_service import write_audit

router = APIRouter(prefix="/api/line", tags=["line"])
DB = Annotated[Session, Depends(get_db)]
log = logging.getLogger("procurement.line")
MAX_BODY = 256 * 1024


@router.post("/webhook", include_in_schema=False)
async def webhook(request: Request, db: DB,
                  x_line_signature: Annotated[str | None, Header()] = None) -> dict:
    body = await request.body()
    if len(body) > MAX_BODY or not line_service.verify_signature(body, x_line_signature):
        raise HTTPException(403, "ลายเซ็นไม่ถูกต้อง")
    try:
        events = (await request.json()).get("events", [])
    except ValueError:
        raise HTTPException(400, "รูปแบบข้อมูลไม่ถูกต้อง") from None

    for ev in events if isinstance(events, list) else []:
        source = ev.get("source") or {}
        if source.get("type") != "group":
            continue   # รับเฉพาะกลุ่ม: แชท 1:1 กับผู้ใช้ไม่ใช่ช่องทางแจ้งเตือนของหน่วยงาน
        gid = str(source.get("groupId", ""))
        if not line_service.LINE_ID.fullmatch(gid):
            continue
        kind = ev.get("type")
        text = str((ev.get("message") or {}).get("text", "")).strip() if kind == "message" else ""
        # แสดง groupId ใน log ของเซิร์ฟเวอร์ (ผู้ดูแลอ่านได้จาก Render → Logs) สำหรับกรณีต้องกรอกด้วยมือ
        log.info("LINE webhook: %s from group %s", kind, gid)
        if kind == "join" or (kind == "message" and text in REGISTER_WORDS):
            _register_group(db, request, gid)
        elif kind == "leave":
            _deactivate_group(db, request, gid)
    return {"ok": True}


REGISTER_WORDS = {"ลงทะเบียน", "register"}


def _register_group(db: Session, request: Request, gid: str) -> None:
    h = blind_index(gid)
    ch = db.scalar(select(NotificationChannel).where(NotificationChannel.line_to_hmac == h))
    if ch is not None:
        return   # รู้จักแล้ว (join ซ้ำ / พิมพ์ลงทะเบียนซ้ำ)
    name = line_service.group_name(gid) or "กลุ่มใหม่ (รอตั้งชื่อ)"
    ch = NotificationChannel(name_th=name, line_to_enc=encrypt_field(gid, "notification_channels.line_to"),
                             line_to_hmac=h, source="WEBHOOK", is_active=False)   # ผู้ดูแลต้องกดเปิดใช้เอง
    db.add(ch)
    db.flush()
    write_audit(db, action="CREATE", user_id=None, request=request, entity_table="notification_channels",
                entity_id=ch.channel_id, new={"name_th": name, "source": "WEBHOOK"})
    log.info("LINE group registered via webhook channel=%s", ch.channel_id)


def _deactivate_group(db: Session, request: Request, gid: str) -> None:
    ch = db.scalar(select(NotificationChannel).where(NotificationChannel.line_to_hmac == blind_index(gid)))
    if ch is None or not ch.is_active:
        return
    ch.is_active = False   # bot ถูกเอาออกจากกลุ่ม → ส่งไม่ถึงอยู่แล้ว ปิดเพื่อไม่ให้ log ล้มเหลวทุกครั้ง
    write_audit(db, action="UPDATE", user_id=None, request=request, entity_table="notification_channels",
                entity_id=ch.channel_id, new={"is_active": False, "reason": "bot left group"})
