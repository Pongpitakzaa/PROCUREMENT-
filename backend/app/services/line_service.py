"""แจ้งเตือนสถานะโครงการ/แชร์เอกสารเข้ากลุ่ม LINE ผ่าน LINE Messaging API (push message).

หมายเหตุสำคัญ: LINE Notify ยุติให้บริการตั้งแต่ 31 มีนาคม 2568 จึงต้องใช้ Messaging API
  1) สร้าง LINE Official Account + Messaging API channel → ได้ Channel Access Token
  2) เชิญ bot เข้ากลุ่มงานพัสดุ → รับ groupId จาก webhook event "join"
  3) บันทึก groupId (เข้ารหัส) ในตาราง notification_channels

ความปลอดภัย:
- ไม่ส่งไฟล์เอกสารหรือข้อมูลส่วนบุคคลเข้า LINE โดยตรง ส่งเพียง "ลิงก์ดาวน์โหลดแบบลงนาม อายุสั้น"
  ผู้รับต้อง login ระบบก่อนดาวน์โหลดจริง (ลิงก์ไม่ใช่สิทธิ์เข้าถึงในตัวเอง)
- ใช้ X-Line-Retry-Key ทำให้ retry ได้ปลอดภัย ไม่ส่งข้อความซ้ำ
"""
from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt

from app.core.config import get_settings

import re

LINE_ID = re.compile(r"^[CU][0-9a-f]{32}$")

STATUS_TH = {
    "SUBMITTED": ("รอพิจารณาอนุมัติ", "#F59E0B"),
    "APPROVED": ("อนุมัติแล้ว", "#16A34A"),
    "REJECTED": ("ส่งกลับแก้ไข", "#DC2626"),
    "DOCUMENT": ("สร้างเอกสารแล้ว", "#2563EB"),
}


class LineSendError(Exception):
    pass


def create_download_token(document_id: int, user_id: int) -> str:
    """Token สำหรับลิงก์ดาวน์โหลด: ผูกกับเอกสาร + มีวันหมดอายุ + purpose แยกจาก access token."""
    s = get_settings()
    now = datetime.now(UTC)
    return jwt.encode({"purpose": "download", "doc": document_id, "by": user_id, "iat": now,
                       "exp": now + timedelta(minutes=s.download_link_minutes)},
                      s.jwt_secret.get_secret_value(), algorithm=s.jwt_algorithm)


def verify_download_token(token: str) -> int:
    s = get_settings()
    payload = jwt.decode(token, s.jwt_secret.get_secret_value(), algorithms=[s.jwt_algorithm],
                         options={"require": ["exp", "doc", "purpose"]})
    if payload["purpose"] != "download":
        raise jwt.InvalidTokenError("wrong purpose")
    return int(payload["doc"])


def build_status_message(*, project_code: str, project_title: str, method_name: str, step_name: str,
                         status: str, budget_text: str, actor_name: str,
                         download_url: str | None = None) -> dict[str, Any]:
    """Flex Message (การ์ดสถานะ) — ข้อความทั้งหมดถูกส่งเป็น JSON text node ของ LINE ไม่ถูกตีความเป็น markup."""
    label, color = STATUS_TH.get(status, (status, "#6B7280"))

    def row(k: str, v: str) -> dict[str, Any]:
        return {"type": "box", "layout": "baseline", "spacing": "sm", "contents": [
            {"type": "text", "text": k, "size": "sm", "color": "#6B7280", "flex": 3},
            {"type": "text", "text": v[:300], "size": "sm", "wrap": True, "flex": 7}]}

    bubble: dict[str, Any] = {
        "type": "bubble",
        "header": {"type": "box", "layout": "vertical", "backgroundColor": color, "contents": [
            {"type": "text", "text": label, "color": "#FFFFFF", "weight": "bold"}]},
        "body": {"type": "box", "layout": "vertical", "spacing": "sm", "contents": [
            {"type": "text", "text": project_title[:200], "weight": "bold", "wrap": True},
            row("เลขที่", project_code), row("วิธี", method_name), row("ขั้นตอน", step_name),
            row("วงเงิน", budget_text), row("โดย", actor_name)]},
    }
    if download_url:
        bubble["footer"] = {"type": "box", "layout": "vertical", "contents": [
            {"type": "button", "style": "primary",
             "action": {"type": "uri", "label": "เปิดเอกสาร (ต้องเข้าสู่ระบบ)", "uri": download_url}}]}
    return {"type": "flex", "altText": f"[{label}] {project_code} {step_name}"[:400], "contents": bubble}


def push_message(to: str, message: dict[str, Any], retry_key: uuid.UUID,
                 client: httpx.Client | None = None, max_attempts: int = 3) -> int:
    """POST /v2/bot/message/push พร้อม retry แบบ exponential backoff สำหรับ 429/5xx.

    คืน HTTP status ที่สำเร็จ; 409 = LINE รับข้อความด้วย retry key นี้ไปแล้ว → ถือว่าสำเร็จ
    """
    s = get_settings()
    if s.line_channel_access_token is None:
        raise LineSendError("ยังไม่ได้ตั้งค่า LINE Channel Access Token")
    headers = {
        "Authorization": f"Bearer {s.line_channel_access_token.get_secret_value()}",
        "Content-Type": "application/json",
        "X-Line-Retry-Key": str(retry_key),
    }
    owns_client = client is None
    client = client or httpx.Client(base_url=s.line_api_base, timeout=10.0)
    try:
        for attempt in range(1, max_attempts + 1):
            try:
                resp = client.post("/v2/bot/message/push", json={"to": to, "messages": [message]},
                                   headers=headers)
            except httpx.TransportError as exc:
                if attempt == max_attempts:
                    raise LineSendError("เชื่อมต่อ LINE ไม่สำเร็จ") from exc
            else:
                if resp.status_code in (200, 409):
                    return resp.status_code
                if resp.status_code not in (429, 500, 502, 503, 504) or attempt == max_attempts:
                    raise LineSendError(f"LINE ตอบกลับ HTTP {resp.status_code}")
            time.sleep(2 ** attempt)   # 2s, 4s
    finally:
        if owns_client:
            client.close()
    raise LineSendError("ส่งข้อความ LINE ไม่สำเร็จ")


# ---------------------------------------------------------------------------
# Webhook (รับ groupId อัตโนมัติ) + แจ้งเตือนอัตโนมัติ
# ---------------------------------------------------------------------------
def verify_signature(body: bytes, signature: str | None) -> bool:
    """X-Line-Signature = base64(HMAC-SHA256(channel secret, body)) — เทียบแบบ constant-time."""
    import base64
    import hashlib
    import hmac
    s = get_settings()
    if s.line_channel_secret is None or not signature:
        return False
    digest = hmac.new(s.line_channel_secret.get_secret_value().encode(), body, hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), signature)


def group_name(group_id: str, client: httpx.Client | None = None) -> str | None:
    """ชื่อกลุ่มจาก GET /v2/bot/group/{groupId}/summary (ไม่มีสิทธิ์/ล้มเหลว → None)."""
    s = get_settings()
    if s.line_channel_access_token is None:
        return None
    owns = client is None
    client = client or httpx.Client(base_url=s.line_api_base, timeout=5.0)
    try:
        resp = client.get(f"/v2/bot/group/{group_id}/summary",
                          headers={"Authorization": f"Bearer {s.line_channel_access_token.get_secret_value()}"})
        if resp.status_code == 200:
            name = str(resp.json().get("groupName", "")).strip()
            return name[:100] or None
    except (httpx.HTTPError, ValueError):
        pass
    finally:
        if owns:
            client.close()
    return None


def build_text_message(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text[:5000]}


def notify_step_change(project_id: int, step_code: str, status: str, actor_name: str, user_id: int | None) -> None:
    """ส่งการ์ดสถานะเข้าทุกกลุ่มที่เปิดใช้ — รันใน background หลังตอบ client แล้ว (ล้มเหลวไม่กระทบงานหลัก).

    บันทึกผลทุกครั้งใน notification_logs เพื่อให้ผู้ดูแลเห็นว่าส่งถึงหรือไม่
    """
    import logging
    from sqlalchemy import select
    from app.core.crypto import decrypt_field
    from app.core.database import SessionLocal
    from app.models import NotificationChannel, NotificationLog, Project, ProjectStep, WorkflowStep
    from app.rules.validators import baht_text

    log = logging.getLogger("procurement.line")
    s = get_settings()
    if not s.line_auto_notify or s.line_channel_access_token is None:
        return
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        step = db.scalar(select(ProjectStep).join(WorkflowStep).where(ProjectStep.project_id == project_id,
                                                                      WorkflowStep.code == step_code))
        channels = db.scalars(select(NotificationChannel).where(NotificationChannel.is_active.is_(True))).all()
        if project is None or step is None or not channels:
            return
        message = build_status_message(
            project_code=project.project_code, project_title=project.title_th, method_name=project.method.name_th,
            step_name=step.step.name_th, status=status,
            budget_text=f"{project.budget_amount:,.2f} บาท ({baht_text(project.budget_amount)})",
            actor_name=actor_name)
        for ch in channels:
            retry_key = uuid.uuid4()
            to = decrypt_field(ch.line_to_enc, "notification_channels.line_to")
            try:
                http_status, result = push_message(to, message, retry_key), "SENT"
            except LineSendError as exc:
                http_status, result = None, "FAILED"
                log.warning("LINE auto-notify failed channel=%s project=%s: %s", ch.channel_id, project_id, exc)
            db.add(NotificationLog(channel_id=ch.channel_id, project_id=project_id, retry_key=retry_key,
                                   status=result, http_status=http_status, sent_by=user_id))
        db.commit()
