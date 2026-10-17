from app.core.security import generate_temp_password, password_problems, role_combination_problems
from tests.test_api_flow import client  # noqa: F401  (fixture client: ฐานข้อมูลทดสอบต่อโมดูล)


def test_password_policy():
    assert password_problems("short1") and password_problems("onlyletterslong")
    assert password_problems("officer2026abc", "officer") == ["ห้ามมีชื่อผู้ใช้อยู่ในรหัสผ่าน"]
    assert password_problems("Correct-Horse-42") == []


def test_temp_password_meets_policy_and_is_random():
    pws = {generate_temp_password() for _ in range(50)}
    assert len(pws) == 50 and all(len(p) == 16 and not password_problems(p) for p in pws)
    assert not any(c in "0O1lI" for p in pws for c in p)        # ไม่มีตัวที่สับสนง่าย


def test_role_segregation_of_duties():
    assert role_combination_problems({"PROCUREMENT_OFFICER"}) == []
    assert role_combination_problems({"HEAD_OF_PROCUREMENT", "EXECUTIVE"}) == []
    assert role_combination_problems({"ADMIN", "HEAD_OF_PROCUREMENT"})          # admin ห้ามทำงานพัสดุ
    assert role_combination_problems({"AUDITOR", "EXECUTIVE"})                  # auditor ต้องอิสระ
    assert role_combination_problems(set())
    assert role_combination_problems({"ROOT"})


def test_full_name_spacing_for_rank_abbreviations():
    """คำย่อยศ (พ.อ.อ., น.อ.) เว้นวรรคก่อนชื่อ · นาย/นาง/นางสาว ไม่เว้น."""
    from app.models import Personnel
    assert Personnel(title_th="นาย", first_name_th="สมชาย", last_name_th="ใจดี").full_name_th == "นายสมชาย ใจดี"
    assert Personnel(title_th="พ.อ.อ.", first_name_th="สมชาย", last_name_th="ใจดี").full_name_th == "พ.อ.อ. สมชาย ใจดี"
    assert Personnel(title_th="น.อ.", first_name_th="สมหญิง", last_name_th="รักงาน").full_name_th == "น.อ. สมหญิง รักงาน"


def test_user_edits_own_profile(client):
    """ผู้ใช้แก้คำนำหน้า/ชื่อ/นามสกุล/ตำแหน่ง/ประเภทบุคลากรของตนเองได้ · ช่องอื่นถูกปฏิเสธ · บันทึก audit."""
    from tests.test_api_flow import login
    officer, admin = login(client, "officer"), login(client, "admin")
    me = client.get("/api/auth/me", headers=officer).json()
    assert me["profile"]["title_th"] == "นาย" and me["profile"]["department_name_th"]
    r = client.patch("/api/auth/me/profile", headers=officer,
                     json={"title_th": "พ.อ.อ.", "position_th": "เจ้าหน้าที่พัสดุอาวุโส", "employment_type": "GOV_EMPLOYEE"})
    assert r.status_code == 200, r.text
    assert r.json()["full_name_th"] == "พ.อ.อ. สมชาย ใจดี" and r.json()["profile"]["employment_type"] == "GOV_EMPLOYEE"
    assert client.get("/api/auth/me", headers=officer).json()["profile"]["position_th"] == "เจ้าหน้าที่พัสดุอาวุโส"
    assert client.patch("/api/auth/me/profile", headers=officer, json={}).status_code == 422
    assert client.patch("/api/auth/me/profile", headers=officer, json={"citizen_id": "1234567890123"}).status_code == 422
    assert client.patch("/api/auth/me/profile", headers=officer, json={"department_id": 2}).status_code == 422
    assert client.patch("/api/auth/me/profile", headers=officer, json={"first_name_th": ""}).status_code == 422
    rows = client.get("/api/admin/audit", headers=admin, params={"limit": 5}).json()
    rows = rows.get("items", []) if isinstance(rows, dict) else rows
    assert any(a.get("entity_table") == "personnel" and (a.get("new_values") or {}).get("via") == "self-profile" for a in rows)
    # คืนค่าเดิมให้เทสต์อื่น
    assert client.patch("/api/auth/me/profile", headers=officer,
                        json={"title_th": "นาย", "position_th": "นักวิชาการพัสดุ", "employment_type": "CIVIL_SERVANT"}).status_code == 200


def test_head_can_approve_own_submission_and_it_is_audited(client):
    """ค่าเริ่มต้น: หัวหน้าเจ้าหน้าที่อนุมัติรายการที่ตนเองส่งได้ · audit บันทึก self_approval=true · เจ้าหน้าที่ยังอนุมัติไม่ได้ (403)."""
    from tests.test_api_flow import login
    from tests.test_line import project_payload
    officer, head, admin = login(client, "officer"), login(client, "head"), login(client, "admin")
    r = client.post("/api/projects", json=project_payload(client, officer, "80000.00", "SELF-2570-001"), headers=head)
    assert r.status_code == 201, r.text
    pid = r.json()["project_id"]
    version = client.get(f"/api/projects/{pid}", headers=head).json()["row_version"]
    r = client.post(f"/api/projects/{pid}/steps/PURCHASE_REQUEST_REPORT/submit", headers=head, json={
        "row_version": version, "data": {
            "doc_no": "พด 0201/2570", "doc_date": "2026-10-12", "reason_th": "หัวหน้าจัดทำเอง", "spec_summary": "x",
            "reference_price": "80000.00", "reference_price_source": "4", "delivery_days": 15,
            "evaluation_criteria": "PRICE", "inspection_committee": [4]}})
    assert r.status_code == 200, r.text
    assert client.post(f"/api/projects/{pid}/steps/PURCHASE_REQUEST_REPORT/decision", headers=officer,
                       json={"approve": True}).status_code == 403
    r = client.post(f"/api/projects/{pid}/steps/PURCHASE_REQUEST_REPORT/decision", headers=head, json={"approve": True})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "APPROVED"
    items = client.get("/api/admin/audit", headers=admin, params={"limit": 5}).json()["items"]
    row = next(a for a in items if a["action"] == "STEP_APPROVE" and a["entity_id"] == f"{pid}:PURCHASE_REQUEST_REPORT")
    assert row["new_values"]["self_approval"] is True
