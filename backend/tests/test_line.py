"""แจ้งเตือน LINE: webhook ลงทะเบียนกลุ่ม, แจ้งอัตโนมัติเมื่อส่งพิจารณา/อนุมัติ, ส่งทดสอบ, ตั้งชื่อ."""
import base64
import hashlib
import hmac
import json

import pytest

from app.services import line_service
from tests import test_api_flow
from tests.test_api_flow import client, login  # noqa: F401  (fixture client สร้างฐานข้อมูลทดสอบใหม่ต่อโมดูล)

GROUP = "C" + "b" * 32
SECRET = "test-channel-secret"


def sign(body: bytes, secret: str = SECRET) -> str:
    return base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()


@pytest.fixture
def line_env(monkeypatch):
    from app.core.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "line_channel_secret", type(s.jwt_secret)(SECRET))
    monkeypatch.setattr(s, "line_auto_notify", True)
    monkeypatch.setattr(line_service, "group_name", lambda gid, client=None: "กลุ่มงานพัสดุ (LINE)")
    sent = []
    monkeypatch.setattr(line_service, "push_message", lambda to, message, retry_key, **_: (sent.append((to, message)), 200)[1])
    return sent


def project_payload(client, officer, budget: str, code: str) -> dict:
    specific = next(m for m in client.get("/api/methods", headers=officer).json() if m["code"] == "SPECIFIC")
    test_api_flow.JUSTIFICATION_56_2_B = next(j["id"] for j in specific["justifications"] if j["clause_ref"] == "มาตรา 56(2)(ข)")
    return test_api_flow.project_payload(budget, code=code)


def post_webhook(client, events, sig=None, body=None):
    raw = body if body is not None else json.dumps({"events": events}).encode()
    headers = {"Content-Type": "application/json", "X-Line-Signature": sig if sig is not None else sign(raw)}
    return client.post("/api/line/webhook", content=raw, headers=headers)


def test_webhook_registers_group_and_rejects_bad_signature(client, line_env):
    admin = login(client, "admin")
    join = [{"type": "join", "source": {"type": "group", "groupId": GROUP}}]
    raw = json.dumps({"events": join}).encode()
    assert post_webhook(client, join, sig=sign(raw, "wrong")).status_code == 403          # ลายเซ็นผิด
    assert post_webhook(client, join, sig="").status_code == 403
    assert post_webhook(client, join).status_code == 200
    assert post_webhook(client, join).status_code == 200                                  # join ซ้ำ ไม่สร้างซ้ำ
    rows = [r for r in client.get("/api/admin/line-channels", headers=admin).json() if r["source"] == "WEBHOOK"]
    assert len(rows) == 1 and rows[0]["name_th"] == "กลุ่มงานพัสดุ (LINE)" and rows[0]["is_active"] is False
    cid = rows[0]["channel_id"]
    # แชท 1:1 และ groupId ผิดรูปแบบ → ไม่ลงทะเบียน
    post_webhook(client, [{"type": "join", "source": {"type": "user", "userId": "U" + "c" * 32}},
                          {"type": "join", "source": {"type": "group", "groupId": "C../x"}}])
    assert len(client.get("/api/admin/line-channels", headers=admin).json()) == len(rows) + _manual_count(client, admin)
    # ลงทะเบียนกลุ่มที่มีอยู่แล้วด้วยมือ → 409
    r = client.post("/api/admin/line-channels", headers=admin, json={"name_th": "ซ้ำ", "line_to": GROUP})
    assert r.status_code == 409
    # ตั้งชื่อ + เปิดใช้
    r = client.patch(f"/api/admin/line-channels/{cid}", headers=admin, json={"name_th": "กลุ่มพัสดุ", "is_active": True})
    assert r.status_code == 200 and r.json() == {"channel_id": cid, "is_active": True, "name_th": "กลุ่มพัสดุ"}
    assert client.patch(f"/api/admin/line-channels/{cid}", headers=admin, json={}).status_code == 422
    # ส่งทดสอบ
    r = client.post(f"/api/admin/line-channels/{cid}/test", headers=admin)
    assert r.status_code == 200 and line_env[-1][0] == GROUP and line_env[-1][1]["type"] == "text"
    assert client.get("/api/admin/line-channels", headers=admin).json()[-1]["last_status"] == "SENT"
    # bot ถูกเอาออกจากกลุ่ม → ปิดอัตโนมัติ
    post_webhook(client, [{"type": "leave", "source": {"type": "group", "groupId": GROUP}}])
    assert next(r for r in client.get("/api/admin/line-channels", headers=admin).json() if r["channel_id"] == cid)["is_active"] is False
    # สถานะการตั้งค่า
    st = client.get("/api/admin/line-status", headers=admin).json()
    assert st["token_configured"] and st["secret_configured"] and st["webhook_url"].endswith("/api/line/webhook")
    assert client.get("/api/admin/line-status").status_code == 401


def _manual_count(client, admin):
    return sum(1 for r in client.get("/api/admin/line-channels", headers=admin).json() if r["source"] == "MANUAL")


def test_auto_notify_on_submit_and_decision(client, line_env):
    officer, head, admin = login(client, "officer"), login(client, "head"), login(client, "admin")
    r = client.post("/api/admin/line-channels", headers=admin, json={"name_th": "แจ้งเตือน", "line_to": "C" + "d" * 32})
    assert r.status_code == 201
    r = client.post("/api/projects", json=project_payload(client, officer, "80000.00", "LINE-2570-001"), headers=officer)
    assert r.status_code == 201, r.text
    pid = r.json()["project_id"]
    assert client.get("/api/line-channels", headers=officer).json()[-1]["name_th"] == "แจ้งเตือน"   # เจ้าหน้าที่เห็นชื่อกลุ่ม
    assert client.get("/api/line-channels", headers=admin).status_code == 403                        # ผู้ดูแลไม่มีสิทธิ์ส่ง

    version = client.get(f"/api/projects/{pid}", headers=officer).json()["row_version"]
    before = len(line_env)
    r = client.post(f"/api/projects/{pid}/steps/PURCHASE_REQUEST_REPORT/submit", headers=officer, json={
        "row_version": version, "data": {
            "doc_no": "พด 0009/2570", "doc_date": "2026-10-12", "reason_th": "ทดสอบ LINE", "spec_summary": "x",
            "reference_price": "80000.00", "reference_price_source": "4", "delivery_days": 15,
            "evaluation_criteria": "PRICE", "inspection_committee": [4]}})
    assert r.status_code == 200, r.text
    sent = line_env[before:]   # TestClient รัน background task ก่อนคืน response
    assert [m["type"] for _, m in sent] == ["flex"] * len(sent) and len(sent) >= 1
    assert "รอพิจารณาอนุมัติ" in json.dumps(sent[-1][1], ensure_ascii=False)
    assert "LINE-2570-001" in json.dumps(sent[-1][1], ensure_ascii=False)

    before = len(line_env)
    r = client.post(f"/api/projects/{pid}/steps/PURCHASE_REQUEST_REPORT/decision", headers=head, json={"approve": True})
    assert r.status_code == 200
    assert "อนุมัติแล้ว" in json.dumps(line_env[-1][1], ensure_ascii=False) and len(line_env) > before


def test_auto_notify_failure_does_not_break_submit(client, line_env, monkeypatch):
    def boom(*_, **__):
        raise line_service.LineSendError("LINE ตอบกลับ HTTP 500")
    monkeypatch.setattr(line_service, "push_message", boom)
    officer, admin = login(client, "officer"), login(client, "admin")
    r = client.post("/api/projects", json=project_payload(client, officer, "90000.00", "LINE-2570-002"), headers=officer)
    assert r.status_code == 201, r.text
    pid = r.json()["project_id"]
    version = client.get(f"/api/projects/{pid}", headers=officer).json()["row_version"]
    r = client.post(f"/api/projects/{pid}/steps/PURCHASE_REQUEST_REPORT/submit", headers=officer, json={
        "row_version": version, "data": {
            "doc_no": "พด 0010/2570", "doc_date": "2026-10-12", "reason_th": "ทดสอบ", "spec_summary": "x",
            "reference_price": "90000.00", "reference_price_source": "4", "delivery_days": 15,
            "evaluation_criteria": "PRICE", "inspection_committee": [4]}})
    assert r.status_code == 200                                                           # งานหลักสำเร็จ
    assert client.get(f"/api/projects/{pid}", headers=officer).json()["steps"][1]["status"] == "SUBMITTED"
    assert client.get("/api/admin/line-channels", headers=admin).json()[-1]["last_status"] == "FAILED"


def test_signature_helper():
    from app.core.config import get_settings
    body = b'{"events":[]}'
    assert line_service.verify_signature(body, None) is False
    s = get_settings()
    s.line_channel_secret = type(s.jwt_secret)(SECRET)
    try:
        assert line_service.verify_signature(body, sign(body)) is True
        assert line_service.verify_signature(body, sign(body + b" ")) is False
    finally:
        s.line_channel_secret = None


def test_line_secrets_tolerate_pasted_whitespace_and_quotes(monkeypatch):
    """ค่าที่วางใน Render/.env มักติดช่องว่าง ขึ้นบรรทัดใหม่ หรือเครื่องหมายคำพูด → ต้องใช้ได้และค่าว่างต้องเท่ากับไม่ตั้ง."""
    from app.core.config import Settings
    monkeypatch.setenv("PROC_LINE_CHANNEL_ACCESS_TOKEN", '  "abc123xyz=" \n')
    monkeypatch.setenv("PROC_LINE_CHANNEL_SECRET", "'secret-value'\t")
    s = Settings()
    assert s.line_channel_access_token.get_secret_value() == "abc123xyz="
    assert s.line_channel_secret.get_secret_value() == "secret-value"
    monkeypatch.setenv("PROC_LINE_CHANNEL_ACCESS_TOKEN", "   ")
    monkeypatch.setenv("PROC_LINE_CHANNEL_SECRET", '""')
    s = Settings()
    assert s.line_channel_access_token is None and s.line_channel_secret is None
