"""ยกเลิกขั้นตอน (ย้อนกลับ) และไฟล์แนบ PDF ต่อขั้นตอน."""
import hashlib
import json

from app.services import line_service
from tests.test_api_flow import client, login  # noqa: F401  (fixture client: ฐานข้อมูลทดสอบต่อโมดูล)
from tests.test_line import project_payload

PDF = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"
PRR = {"doc_no": "พด 0301/2570", "doc_date": "2026-10-12", "reason_th": "ทดสอบ", "spec_summary": "x",
       "reference_price": "80000.00", "reference_price_source": "4", "delivery_days": 15,
       "evaluation_criteria": "PRICE", "inspection_committee": [4]}


def _new_project(client, who, code):
    r = client.post("/api/projects", json=project_payload(client, who, "80000.00", code), headers=who)
    assert r.status_code == 201, r.text
    return r.json()["project_id"]


def _submit(client, who, pid, step, data):
    version = client.get(f"/api/projects/{pid}", headers=who).json()["row_version"]
    return client.post(f"/api/projects/{pid}/steps/{step}/submit", headers=who, json={"data": data, "row_version": version})


def _status(client, who, pid, step):
    return next(s["status"] for s in client.get(f"/api/projects/{pid}", headers=who).json()["steps"] if s["code"] == step)


def test_revert_submitted_and_approved_steps(client, monkeypatch):
    sent = []
    monkeypatch.setattr(line_service, "push_message", lambda to, message, retry_key, **_: (sent.append(message), 200)[1])
    officer, head, admin, director = login(client, "officer"), login(client, "head"), login(client, "admin"), login(client, "director")
    client.post("/api/admin/line-channels", headers=admin, json={"name_th": "กลุ่มทดสอบ", "line_to": "C" + "f" * 32})
    pid = _new_project(client, officer, "RVT-2570-001")
    revert = f"/api/projects/{pid}/steps/PURCHASE_REQUEST_REPORT/revert"

    # ยังไม่ส่งพิจารณา → ไม่มีอะไรให้ยกเลิก · ต้องระบุเหตุผล
    assert client.post(revert, headers=officer, json={"reason": "ทดสอบ"}).status_code == 422
    assert _submit(client, officer, pid, "PURCHASE_REQUEST_REPORT", PRR).status_code == 200
    assert client.post(revert, headers=officer, json={"reason": "x"}).status_code == 422     # เหตุผลสั้นเกิน
    assert client.post(revert, headers=director, json={"reason": "ผู้บริหารขอยกเลิก"}).status_code == 200  # ผู้มีสิทธิ์อนุมัติ
    assert _status(client, officer, pid, "PURCHASE_REQUEST_REPORT") == "IN_PROGRESS"
    assert "ยกเลิกขั้นตอน" in json.dumps(sent[-1], ensure_ascii=False) and "ผู้บริหารขอยกเลิก" in json.dumps(sent[-1], ensure_ascii=False)
    # ข้อมูลในฟอร์มยังอยู่ → ส่งใหม่ได้ทันที
    form = client.get(f"/api/projects/{pid}/steps/PURCHASE_REQUEST_REPORT/form", headers=officer).json()
    assert form["values"]["doc_no"] == "พด 0301/2570"
    assert _submit(client, officer, pid, "PURCHASE_REQUEST_REPORT", PRR).status_code == 200
    # ผู้ส่งเองยกเลิกได้ (SUBMITTED)
    assert client.post(revert, headers=officer, json={"reason": "กรอกเลขหนังสือผิด"}).status_code == 200
    assert _submit(client, officer, pid, "PURCHASE_REQUEST_REPORT", PRR).status_code == 200
    # อนุมัติแล้ว: เจ้าหน้าที่ยกเลิกไม่ได้ หัวหน้ายกเลิกได้
    assert client.post(f"/api/projects/{pid}/steps/PURCHASE_REQUEST_REPORT/decision", headers=head, json={"approve": True}).status_code == 200
    r = client.post(revert, headers=officer, json={"reason": "ขอแก้ไขหลังอนุมัติ"})
    assert r.status_code == 422 and r.json()["violations"][0]["code"] == "REVERT_NOT_ALLOWED"
    # ขั้นถัดไปส่งแล้ว → ต้องยกเลิกขั้นถัดไปก่อน
    assert client.post("/api/vendors", headers=officer, json={
        "tax_id": "0105536092641", "vendor_type": "JURISTIC", "name_th": "บริษัท ตัวอย่างไอที จำกัด",
        "address_th": "99 ถนนพหลโยธิน"}).status_code in (201, 422)
    price = {"doc_no": "พด 0302/2570", "doc_date": "2026-10-13", "vendor_tax_id": "0105536092641",
             "vendor_name": "บริษัท ตัวอย่างไอที จำกัด", "quoted_amount": "80000.00", "agreed_amount": "79500.00"}
    assert _submit(client, officer, pid, "PRICE_AGREEMENT", price).status_code == 200
    r = client.post(revert, headers=head, json={"reason": "ย้อนข้ามขั้น"})
    assert r.status_code == 422 and r.json()["violations"][0]["code"] == "LATER_STEP_DONE"
    assert client.post(f"/api/projects/{pid}/steps/PRICE_AGREEMENT/revert", headers=head, json={"reason": "ยกเลิกราคา"}).status_code == 200
    assert client.post(revert, headers=head, json={"reason": "แก้รายงานขอซื้อ"}).status_code == 200
    assert _status(client, officer, pid, "PURCHASE_REQUEST_REPORT") == "IN_PROGRESS"
    assert client.get(f"/api/projects/{pid}", headers=officer).json()["status"] == "IN_PROGRESS"
    # ขั้นสร้างโครงการยกเลิกไม่ได้
    r = client.post(f"/api/projects/{pid}/steps/CREATE_PROJECT/revert", headers=head, json={"reason": "ลองยกเลิก"})
    assert r.status_code == 422 and r.json()["violations"][0]["code"] == "STEP_NOT_REVERTIBLE"
    items = client.get("/api/admin/audit", headers=admin, params={"limit": 20}).json()["items"]
    assert any(a["action"] == "STEP_REVERT" and a["new_values"]["reason"] == "แก้รายงานขอซื้อ" for a in items)


def test_pdf_attachments_per_step(client):
    officer, head, admin, director = login(client, "officer"), login(client, "head"), login(client, "admin"), login(client, "director")
    pid = _new_project(client, officer, "ATT-2570-001")
    base = f"/api/projects/{pid}/steps/PURCHASE_REQUEST_REPORT/attachments"
    assert client.get(base, headers=officer).json() == []

    up = lambda who, name, data: client.post(base, headers=who, files={"file": (name, data, "application/pdf")})  # noqa: E731
    assert up(officer, "ไม่ใช่.pdf", b"MZ\x90\x00 not a pdf").status_code == 422
    assert up(officer, "big.pdf", b"%PDF-1.4" + b"0" * (10 * 1024 * 1024)).status_code == 413
    assert up(officer, "evil.pdf", PDF + b"<< /S /JavaScript /JS (app.alert(1)) >>").status_code == 422
    assert up(admin, "x.pdf", PDF).status_code == 403                                      # ผู้ดูแลระบบไม่มีสิทธิ์งานพัสดุ
    r = up(officer, "../../ใบเสนอราคา.PDF", PDF)
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["file_name"] == "ใบเสนอราคา.PDF" and a["size_bytes"] == len(PDF) and a["sha256"] == hashlib.sha256(PDF).hexdigest()
    assert a["uploaded_by"].endswith("ใจดี")
    aid = a["attachment_id"]
    assert client.get(base, headers=director).json()[0]["attachment_id"] == aid             # ผู้บริหารดูรายการได้

    # เปิดดู: inline PDF + nosniff · ดาวน์โหลด: attachment
    r = client.get(f"/api/attachments/{aid}", headers=director)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/pdf") and r.content == PDF
    assert r.headers["content-disposition"].startswith("inline") and r.headers["x-content-type-options"] == "nosniff"
    assert client.get(f"/api/attachments/{aid}?download=true", headers=officer).headers["content-disposition"].startswith("attachment")
    assert client.get(f"/api/attachments/{aid}").status_code == 401                          # ต้อง login

    # ลบ: ผู้แนบเอง หรือผู้มีสิทธิ์อนุมัติ
    r2 = up(head, "หัวหน้าแนบ.pdf", PDF)
    assert r2.status_code == 201
    assert client.delete(f"/api/attachments/{r2.json()['attachment_id']}", headers=officer).status_code == 403
    assert client.delete(f"/api/attachments/{aid}", headers=head).status_code == 204
    assert client.delete(f"/api/attachments/{aid}", headers=head).status_code == 404
    assert [x["file_name"] for x in client.get(base, headers=officer).json()] == ["หัวหน้าแนบ.pdf"]
    items = client.get("/api/admin/audit", headers=admin, params={"limit": 20}).json()["items"]
    assert {a["action"] for a in items} >= {"ATTACHMENT_UPLOAD", "ATTACHMENT_VIEW", "ATTACHMENT_DELETE"}
