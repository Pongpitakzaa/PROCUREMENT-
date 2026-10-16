"""แจ้งเตือนใกล้ครบกำหนดส่งมอบ: คำนวณกำหนดจากใบสั่งซื้อ ส่ง milestone ละครั้ง เลยกำหนดแจ้งซ้ำแบบจำกัด."""
import json
from datetime import date, timedelta

import pytest

from app.services import delivery_service, line_service
from tests.test_api_flow import VENDOR_TAX_ID, client, login  # noqa: F401  (fixture client จากโมดูล flow)
from tests.test_line import project_payload

PO_DUE = date(2026, 12, 15)


@pytest.fixture
def sent(monkeypatch):
    out = []
    monkeypatch.setattr(line_service, "push_message", lambda to, message, retry_key, **_: (out.append((to, message)), 200)[1])
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "line_auto_notify", False)   # ตัดการ์ดสถานะออก เหลือเฉพาะการ์ดครบกำหนด
    return out


def _approved_po_project(client, code: str) -> int:
    officer, head, director = login(client, "officer"), login(client, "head"), login(client, "director")
    r = client.post("/api/projects", json=project_payload(client, officer, "80000.00", code), headers=officer)
    assert r.status_code == 201, r.text
    pid = r.json()["project_id"]
    if client.get("/api/vendors", params={"q": VENDOR_TAX_ID}, headers=officer).json() == []:
        assert client.post("/api/vendors", headers=officer, json={
            "tax_id": VENDOR_TAX_ID, "vendor_type": "JURISTIC", "name_th": "บริษัท ตัวอย่างไอที จำกัด",
            "address_th": "99 ถนนพหลโยธิน กรุงเทพมหานคร"}).status_code == 201

    def submit(step, data, who=officer):
        version = client.get(f"/api/projects/{pid}", headers=who).json()["row_version"]
        r = client.post(f"/api/projects/{pid}/steps/{step}/submit", json={"data": data, "row_version": version}, headers=who)
        assert r.status_code == 200, r.text

    def approve(step, who=head):
        r = client.post(f"/api/projects/{pid}/steps/{step}/decision", json={"approve": True}, headers=who)
        assert r.status_code == 200, r.text

    submit("PURCHASE_REQUEST_REPORT", {
        "doc_no": "พด 0101/2570", "doc_date": "2026-10-12", "reason_th": "ทดสอบส่งมอบ", "spec_summary": "x",
        "reference_price": "80000.00", "reference_price_source": "4", "delivery_days": 30,
        "evaluation_criteria": "PRICE", "inspection_committee": [4]})
    approve("PURCHASE_REQUEST_REPORT")
    submit("PRICE_AGREEMENT", {"doc_no": "พด 0102/2570", "doc_date": "2026-10-13", "vendor_tax_id": VENDOR_TAX_ID,
                               "vendor_name": "บริษัท ตัวอย่างไอที จำกัด", "quoted_amount": "80000.00",
                               "agreed_amount": "79500.00"})
    approve("PRICE_AGREEMENT")
    submit("AWARD_APPROVAL", {"doc_no": "พด 0103/2570", "doc_date": "2026-10-14", "winner_tax_id": VENDOR_TAX_ID,
                              "award_amount": "79500.00"})
    approve("AWARD_APPROVAL", who=director)
    submit("PURCHASE_ORDER", {"po_no": "ใบสั่งซื้อ 7/2570", "po_date": "2026-11-15",
                              "delivery_due_date": PO_DUE.isoformat(), "penalty_rate_percent": "0.10"})
    approve("PURCHASE_ORDER")
    return pid


def test_due_date_from_purchase_order_and_milestones(client, sent):
    from app.core.database import SessionLocal
    admin = login(client, "admin")
    assert client.post("/api/admin/line-channels", headers=admin,
                       json={"name_th": "กลุ่มส่งมอบ", "line_to": "C" + "e" * 32}).status_code == 201
    pid = _approved_po_project(client, "DLV-2570-001")

    with SessionLocal() as db:
        due = [p for p in delivery_service.due_projects(db) if p.project_id == pid]
        assert len(due) == 1 and due[0].due_date == PO_DUE and due[0].source == "PO" and due[0].po_no == "ใบสั่งซื้อ 7/2570"

        # 10 วันก่อนกำหนด: ยังไม่ถึง milestone แรก (7 วัน) → ไม่ส่ง
        r = delivery_service.run_reminders(db, today=PO_DUE - timedelta(days=10), force=True)
        assert r["sent"] == 0 and r["skipped_reason"] is None
        # 7 วันก่อน: ส่ง D7 ครั้งเดียว แม้เรียกซ้ำ (ตัวตั้งเวลารายชั่วโมง)
        assert delivery_service.run_reminders(db, today=PO_DUE - timedelta(days=7), force=True)["sent"] == 1
        assert delivery_service.run_reminders(db, today=PO_DUE - timedelta(days=7), force=True)["sent"] == 0
        card = json.dumps(sent[-1][1], ensure_ascii=False)
        assert "ครบกำหนดส่งมอบในอีก 7 วัน" in card and "DLV-2570-001" in card and "15 ธันวาคม 2569" in card
        assert sent[-1][0] == "C" + "e" * 32
        # 5 วันก่อน (ระบบหยุดไป 2 วัน): ข้าม D7 ที่ส่งแล้ว ไปส่ง D3? ไม่ — milestone ใกล้สุดที่ครอบ 5 วันคือ D7 ซึ่งส่งแล้ว → ไม่ส่งซ้ำ
        assert delivery_service.run_reminders(db, today=PO_DUE - timedelta(days=5), force=True)["sent"] == 0
        assert delivery_service.run_reminders(db, today=PO_DUE - timedelta(days=1), force=True)["sent"] == 1
        assert "พรุ่งนี้" in json.dumps(sent[-1][1], ensure_ascii=False)
        assert delivery_service.run_reminders(db, today=PO_DUE, force=True)["sent"] == 1
        assert "วันนี้" in json.dumps(sent[-1][1], ensure_ascii=False)
        # เลยกำหนด: แจ้งทุก 7 วัน รวมไม่เกิน 4 ครั้ง และบอกอัตราค่าปรับจากใบสั่งซื้อ
        assert delivery_service.run_reminders(db, today=PO_DUE + timedelta(days=2), force=True)["sent"] == 1
        over = json.dumps(sent[-1][1], ensure_ascii=False)
        assert "เลยกำหนดส่งมอบแล้ว 2 วัน" in over and "ร้อยละ 0.10" in over
        assert delivery_service.run_reminders(db, today=PO_DUE + timedelta(days=6), force=True)["sent"] == 0
        assert delivery_service.run_reminders(db, today=PO_DUE + timedelta(days=9), force=True)["sent"] == 1
        assert delivery_service.run_reminders(db, today=PO_DUE + timedelta(days=40), force=True)["sent"] == 0   # ครบ 4 ครั้งแล้ว? ยังไม่ครบ
        assert delivery_service.run_reminders(db, today=PO_DUE + timedelta(days=16), force=True)["sent"] == 1
        assert delivery_service.run_reminders(db, today=PO_DUE + timedelta(days=23), force=True)["sent"] == 1
        assert delivery_service.run_reminders(db, today=PO_DUE + timedelta(days=30), force=True)["sent"] == 0   # เกิน 4 ครั้ง หยุด

        # บันทึกผลใน notification_logs ทุกครั้ง
        from sqlalchemy import func, select
        from app.models import NotificationLog
        assert db.scalar(select(func.count()).select_from(NotificationLog).where(NotificationLog.project_id == pid)) == 7

    # หน้าเว็บ: รายการใกล้ครบกำหนด (เรียงใกล้สุดก่อน) และสถานะสำหรับผู้ดูแล
    officer = login(client, "officer")
    with SessionLocal() as db:
        rows = delivery_service.upcoming(db, within_days=14, today=PO_DUE - timedelta(days=3))
    assert [r["project_code"] for r in rows if r["project_id"] == pid] == ["DLV-2570-001"]
    assert next(r for r in rows if r["project_id"] == pid)["days_left"] == 3
    assert client.get("/api/deliveries/upcoming", headers=officer).status_code == 200
    status = client.get("/api/admin/delivery-reminders", headers=admin).json()
    assert status["enabled"] is True and status["days"] == [7, 3, 1, 0] and status["last_sent_at"]
    assert client.get("/api/admin/delivery-reminders", headers=officer).status_code == 403
    r = client.post("/api/admin/delivery-reminders/run", headers=admin)
    assert r.status_code == 200 and r.json()["skipped_reason"] in (None, "NO_ACTIVE_CHANNEL")


def test_reminder_skips_when_disabled_or_no_token(client, sent, monkeypatch):
    from app.core.config import get_settings
    from app.core.database import SessionLocal
    s = get_settings()
    with SessionLocal() as db:
        monkeypatch.setattr(s, "delivery_reminder_enabled", False)
        assert delivery_service.run_reminders(db, force=True)["skipped_reason"] == "DISABLED"
        monkeypatch.setattr(s, "delivery_reminder_enabled", True)
        monkeypatch.setattr(s, "line_channel_access_token", None)
        assert delivery_service.run_reminders(db, force=True)["skipped_reason"] == "NO_LINE_TOKEN"
    assert sent == []


def test_due_date_estimated_from_contract(client, sent):
    """วิธีที่ลงนามสัญญา (ไม่มีช่องกำหนดส่งมอบ) → วันอนุมัติสัญญา + delivery_days ของโครงการ."""
    from datetime import UTC, datetime
    from app.core.database import SessionLocal
    from app.models import Project, ProjectStep, WorkflowStep
    from sqlalchemy import select
    officer = login(client, "officer")
    payload = project_payload(client, officer, "600000.00", "DLV-2570-002")
    selection = next(m for m in client.get("/api/methods", headers=officer).json() if m["code"] == "SELECTION")
    payload.update(method_code="SELECTION", justification_id=selection["justifications"][0]["id"] if selection["justifications"] else None,
                   delivery_days=45, items=[{"description": "ครุภัณฑ์", "quantity": "1", "unit_th": "ชุด", "unit_price": "600000.00"}])
    r = client.post("/api/projects", json=payload, headers=officer)
    assert r.status_code == 201, r.text
    pid = r.json()["project_id"]
    signed = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
    with SessionLocal() as db:
        step = db.scalar(select(ProjectStep).join(WorkflowStep).where(ProjectStep.project_id == pid, WorkflowStep.code == "CONTRACT"))
        step.status, step.approved_at = "APPROVED", signed          # จำลองการลงนามสัญญาโดยตรง (เส้นทางเต็มทดสอบใน flow)
        db.get(Project, pid).status = "CONTRACTED"
        db.commit()
        p = next(x for x in delivery_service.due_projects(db) if x.project_id == pid)
        assert p.source == "CONTRACT" and p.due_date == date(2026, 12, 16)
        assert delivery_service.run_reminders(db, today=date(2026, 12, 16), force=True)["sent"] >= 0
    card = json.dumps(sent[-1][1], ensure_ascii=False) if sent else ""
    assert "ประมาณจากวันลงนามสัญญา" in card and "DLV-2570-002" in card
