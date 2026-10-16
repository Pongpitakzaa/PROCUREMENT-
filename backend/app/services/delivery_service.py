"""แจ้งเตือนใกล้ครบกำหนดส่งมอบ — ส่งการ์ดเข้ากลุ่ม LINE ที่เปิดใช้ ล่วงหน้า 7/3/1 วัน วันครบกำหนด และเมื่อเลยกำหนด.

กำหนดส่งมอบของโครงการมาจาก (เรียงตามลำดับ):
  1) ช่อง "กำหนดส่งมอบภายในวันที่" ของขั้นออกใบสั่งซื้อ/สั่งจ้าง (PURCHASE_ORDER) ที่อนุมัติแล้ว
  2) วันที่อนุมัติขั้นลงนามสัญญา (CONTRACT) + กำหนดเวลาส่งมอบ (delivery_days) ของโครงการ
โครงการที่ยกเลิกไม่แจ้ง · แต่ละ milestone ส่งครั้งเดียวต่อกำหนดส่งมอบ (ตาราง delivery_reminders)
ถ้าเลยกำหนดแล้วแจ้งซ้ำทุก 7 วัน รวมไม่เกิน 4 ครั้ง (ประมาณ 1 เดือน) เพราะระบบยังไม่มีขั้นบันทึกการตรวจรับ
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import DeliveryReminder, NotificationChannel, NotificationLog, Project, ProjectStep, WorkflowStep
from app.rules.validators import thai_date
from app.services import line_service

log = logging.getLogger("procurement.delivery")
BANGKOK = ZoneInfo("Asia/Bangkok")
_RUN_LOCK = 7_240_002           # pg_advisory_lock กันหลาย worker ส่งพร้อมกัน
OVERDUE_REPEAT_DAYS = 7
OVERDUE_MAX_REPEATS = 4
DUE_STEPS = ("PURCHASE_ORDER", "CONTRACT")


@dataclass(frozen=True)
class DueProject:
    project_id: int
    project_code: str
    title_th: str
    method_name: str
    due_date: date
    source: str              # "PO" = จากใบสั่งซื้อ · "CONTRACT" = ประมาณจากวันลงนาม + delivery_days
    po_no: str | None
    penalty_rate: str | None
    budget_amount: Any

    def days_left(self, today: date) -> int:
        return (self.due_date - today).days


def today_th() -> date:
    return datetime.now(BANGKOK).date()


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def due_projects(db: Session) -> list[DueProject]:
    """โครงการที่มีกำหนดส่งมอบ (ยังไม่ยกเลิก) พร้อมที่มาของวันที่."""
    rows = db.execute(
        select(Project, ProjectStep, WorkflowStep.code)
        .join(ProjectStep, ProjectStep.project_id == Project.project_id)
        .join(WorkflowStep, WorkflowStep.step_id == ProjectStep.step_id)
        .where(WorkflowStep.code.in_(DUE_STEPS), ProjectStep.status == "APPROVED",
               Project.status.notin_(("CANCELLED",)))
        .order_by(Project.project_id)).all()
    out: list[DueProject] = []
    for project, step, code in rows:
        data = step.step_data or {}
        if code == "PURCHASE_ORDER":
            due, source = _parse_date(data.get("delivery_due_date")), "PO"
        else:
            due = (step.approved_at.astimezone(BANGKOK).date() + timedelta(days=project.delivery_days)
                   if step.approved_at else None)
            source = "CONTRACT"
        if due is None:
            continue
        rate = data.get("penalty_rate_percent")
        out.append(DueProject(project.project_id, project.project_code, project.title_th, project.method.name_th,
                              due, source, data.get("po_no"), f"{rate}" if rate not in (None, "") else None,
                              project.budget_amount))
    return out


def milestone_for(p: DueProject, today: date, sent: set[str], days: list[int]) -> str | None:
    """milestone ที่ควรส่งวันนี้ (ส่งอันที่ "ใกล้ที่สุด" ที่ยังไม่เคยส่ง — ถ้าระบบหยุดไปหลายวันจะไม่ส่งย้อนหลังทีละใบ)."""
    left = p.days_left(today)
    if left < 0:
        overdue_days = -left
        n = (overdue_days - 1) // OVERDUE_REPEAT_DAYS          # 0 = เลยกำหนดวันที่ 1–7, 1 = 8–14 ...
        if n >= OVERDUE_MAX_REPEATS:
            return None
        key = f"OVERDUE{n}"
        return None if key in sent else key
    candidates = [d for d in sorted(days) if d >= left]
    if not candidates:
        return None
    key = f"D{candidates[0]}"
    return None if key in sent else key


def build_delivery_message(p: DueProject, today: date, base_url: str) -> dict[str, Any]:
    left = p.days_left(today)
    if left > 1:
        label, color = f"ครบกำหนดส่งมอบในอีก {left} วัน", "#F59E0B"
    elif left == 1:
        label, color = "ครบกำหนดส่งมอบพรุ่งนี้", "#EA580C"
    elif left == 0:
        label, color = "ครบกำหนดส่งมอบวันนี้", "#DC2626"
    else:
        label, color = f"เลยกำหนดส่งมอบแล้ว {-left} วัน", "#7F1D1D"

    def row(k: str, v: str) -> dict[str, Any]:
        return {"type": "box", "layout": "baseline", "spacing": "sm", "contents": [
            {"type": "text", "text": k, "size": "sm", "color": "#6B7280", "flex": 3},
            {"type": "text", "text": v[:300], "size": "sm", "wrap": True, "flex": 7}]}

    rows = [row("เลขที่", p.project_code), row("วิธี", p.method_name),
            row("กำหนดส่งมอบ", thai_date(p.due_date) + (" (ประมาณจากวันลงนามสัญญา)" if p.source == "CONTRACT" else ""))]
    if p.po_no:
        rows.append(row("ใบสั่งซื้อ", p.po_no))
    rows.append(row("วงเงิน", f"{p.budget_amount:,.2f} บาท"))
    if left < 0 and p.penalty_rate:
        rows.append(row("ค่าปรับ", f"ร้อยละ {p.penalty_rate} ต่อวัน (ระเบียบ ข้อ 162) — ตรวจสอบและแจ้งผู้ประกอบการ"))
    elif left >= 0:
        rows.append(row("ดำเนินการ", "ติดตามผู้ประกอบการ และเตรียมคณะกรรมการตรวจรับพัสดุ"))
    bubble = {
        "type": "bubble",
        "header": {"type": "box", "layout": "vertical", "backgroundColor": color, "contents": [
            {"type": "text", "text": "⏰ " + label, "color": "#FFFFFF", "weight": "bold", "wrap": True}]},
        "body": {"type": "box", "layout": "vertical", "spacing": "sm", "contents": [
            {"type": "text", "text": p.title_th[:200], "weight": "bold", "wrap": True}, *rows]},
        "footer": {"type": "box", "layout": "vertical", "contents": [
            {"type": "button", "style": "secondary",
             "action": {"type": "uri", "label": "เปิดโครงการ (ต้องเข้าสู่ระบบ)",
                        "uri": f"{base_url}/?project={p.project_id}"}}]},
    }
    return {"type": "flex", "altText": f"[{label}] {p.project_code}"[:400], "contents": bubble}


def run_reminders(db: Session, *, today: date | None = None, force: bool = False) -> dict[str, Any]:
    """ตรวจทุกโครงการแล้วส่งการ์ดที่ถึงกำหนด — idempotent: เรียกกี่ครั้งต่อวันก็ส่งแต่ละ milestone ครั้งเดียว.

    force=True (ปุ่ม "ตรวจเดี๋ยวนี้" ของผู้ดูแล) ข้ามเงื่อนไขเวลาเริ่มส่ง แต่ไม่ข้ามการกันส่งซ้ำ
    """
    s = get_settings()
    today = today or today_th()
    summary: dict[str, Any] = {"checked": 0, "sent": 0, "failed": 0, "skipped_reason": None, "today": today.isoformat()}
    if not s.delivery_reminder_enabled:
        summary["skipped_reason"] = "DISABLED"
        return summary
    if s.line_channel_access_token is None:
        summary["skipped_reason"] = "NO_LINE_TOKEN"
        return summary
    if not force and datetime.now(BANGKOK).hour < s.delivery_reminder_hour:
        summary["skipped_reason"] = "BEFORE_HOUR"
        return summary
    if not db.scalar(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": _RUN_LOCK}):
        summary["skipped_reason"] = "ALREADY_RUNNING"
        return summary

    channels = db.scalars(select(NotificationChannel).where(NotificationChannel.is_active.is_(True))).all()
    projects = due_projects(db)
    summary["checked"] = len(projects)
    if not channels:
        summary["skipped_reason"] = "NO_ACTIVE_CHANNEL"
        return summary
    sent_rows = db.execute(select(DeliveryReminder.project_id, DeliveryReminder.milestone, DeliveryReminder.due_date)).all()
    sent_by_project: dict[tuple[int, date], set[str]] = {}
    for pid, m, d in sent_rows:
        sent_by_project.setdefault((pid, d), set()).add(m)
    base = s.public_base_url.rstrip("/")

    for p in projects:
        key = milestone_for(p, today, sent_by_project.get((p.project_id, p.due_date), set()), s.delivery_reminder_days)
        if key is None:
            continue
        # บันทึกก่อนส่ง: ถ้าส่งแล้วล้มเหลวจะไม่วนส่งซ้ำทุกชั่วโมง (ผู้ดูแลเห็น FAILED ใน notification_logs)
        db.add(DeliveryReminder(project_id=p.project_id, milestone=key, due_date=p.due_date))
        db.flush()
        message = build_delivery_message(p, today, base)
        for ch in channels:
            retry_key = uuid.uuid4()
            to = line_service.decrypt_channel(ch)
            try:
                http_status, result = line_service.push_message(to, message, retry_key), "SENT"
                summary["sent"] += 1
            except line_service.LineSendError as exc:
                http_status, result = None, "FAILED"
                summary["failed"] += 1
                log.warning("delivery reminder failed channel=%s project=%s: %s", ch.channel_id, p.project_id, exc)
            db.add(NotificationLog(channel_id=ch.channel_id, project_id=p.project_id, retry_key=retry_key,
                                   status=result, http_status=http_status, sent_by=None))
    db.commit()
    return summary


def upcoming(db: Session, *, within_days: int = 14, today: date | None = None) -> list[dict[str, Any]]:
    """รายการโครงการใกล้ครบ/เลยกำหนดส่งมอบ สำหรับหน้าเว็บ (เรียงใกล้สุดก่อน)."""
    today = today or today_th()
    out = []
    for p in due_projects(db):
        left = p.days_left(today)
        if left <= within_days:
            out.append({"project_id": p.project_id, "project_code": p.project_code, "title_th": p.title_th,
                        "due_date": p.due_date.isoformat(), "days_left": left, "source": p.source, "po_no": p.po_no})
    out.sort(key=lambda r: r["days_left"])
    return out


def last_run_info(db: Session) -> dict[str, Any]:
    row = db.execute(select(DeliveryReminder.sent_at).order_by(DeliveryReminder.sent_at.desc()).limit(1)).first()
    return {"last_sent_at": row[0].isoformat() if row else None}


# ---------------------------------------------------------------------------
# ตัวตั้งเวลาในโปรเซส API: ตรวจทุกชั่วโมง (และทันทีตอนเริ่ม) — ไม่ต้องมี cron/worker แยก (Render แผนฟรีไม่มี cron)
# ---------------------------------------------------------------------------
def scheduler_loop(stop_event, interval_seconds: int = 3600) -> None:
    from app.core.database import SessionLocal
    while not stop_event.is_set():
        try:
            with SessionLocal() as db:
                result = run_reminders(db)
            if result["sent"] or result["failed"]:
                log.info("delivery reminders: %s", result)
        except Exception:   # noqa: BLE001 — ตัวตั้งเวลาต้องไม่ตายเพราะรอบเดียวพัง
            log.exception("delivery reminder run failed")
        stop_event.wait(interval_seconds)
