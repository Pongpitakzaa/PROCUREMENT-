"""ทดสอบการตรวจสอบข้อมูลและความปลอดภัยกับระบบที่รันอยู่ (API + PostgreSQL) — กลุ่ม A, B, C.

- A/C: ยิงตรงไปที่ API (ข้ามหน้าเว็บ) เพื่อพิสูจน์ว่า backend บังคับกฎเอง
- B: แก้ข้อมูลตรงในฐานข้อมูลภายใน transaction แล้ว ROLLBACK ทุกครั้ง (ข้อ tamper ต้องใช้ role ที่เป็นเจ้าของตาราง)
สร้างข้อมูลทดสอบของตัวเอง (โครงการ VAL-*, ผู้ประกอบการ, ผู้ใช้ชั่วคราว) — ใช้กับระบบทดสอบเท่านั้น
ผลลัพธ์: $AUDIT_OUT/results.json · exit code 1 ถ้ามีข้อไม่ผ่าน
"""
import base64
import io
import json
import os
import re
import sys
import time
import zipfile

import httpx
import psycopg

from _guard import API_URL, DB_DSN, OUT_DIR, USERS, ensure_safe_target, password

ensure_safe_target()
PW = password()
c = httpx.Client(base_url=API_URL, timeout=60)
results: list[dict] = []
STAMP = str(int(time.time()))[-6:]
A, B, C = "A. ตรวจข้อมูล (backend)", "B. ฐานข้อมูล (ด่านสุดท้าย)", "C. ความปลอดภัย / สิทธิ์"


def check(cat: str, name: str, expected: str, ok: bool, actual: str) -> None:
    results.append({"cat": cat, "name": name, "expected": expected, "actual": actual, "ok": bool(ok)})
    print(f"{'PASS' if ok else 'FAIL'}  [{cat[:1]}] {name} → {actual}")


def tok(u: str, pw: str = PW) -> dict:
    r = c.post("/api/auth/login", json={"username": u, "password": pw})
    if r.status_code != 200:
        sys.exit(f"login {u} ไม่สำเร็จ (HTTP {r.status_code}) — รัน seed_demo.py และตรวจ AUDIT_PASSWORD")
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def codes(r: httpx.Response) -> list[str]:
    try:
        return [v["code"] for v in r.json().get("violations", [])]
    except ValueError:
        return []


def tax_id(base12: str) -> str:
    s = sum(int(base12[i]) * (13 - i) for i in range(12))
    return base12 + str((11 - s % 11) % 10)


officer, head, admin, director = (tok(USERS[k]) for k in ("officer", "head", "admin", "director"))
methods = c.get("/api/methods", headers=officer).json()
J56_2B = next(j["id"] for m in methods if m["code"] == "SPECIFIC" for j in m["justifications"]
              if j["clause_ref"] == "มาตรา 56(2)(ข)")
DEPT = c.get("/api/departments", headers=officer).json()[0]["department_id"]


def project(budget="150000.00", **over):
    p = {"project_code": f"VAL-{STAMP}", "fiscal_year_be": 2570, "title_th": "ทดสอบการตรวจสอบข้อมูล",
         "reason_th": "ทดสอบ", "department_id": DEPT, "method_code": "SPECIFIC", "justification_id": J56_2B,
         "procurement_type": "SERVICE", "budget_amount": budget, "delivery_days": 30,
         # คำแรกของรายการไม่ซ้ำกันในแต่ละรอบ → การรันซ้ำไม่ถูกนับเป็นการซื้อลักษณะเดียวกัน (กฎแบ่งซื้อแบ่งจ้าง)
         "items": [{"description": f"งานทดสอบ{STAMP} ระบบ", "quantity": "1", "unit_th": "งาน", "unit_price": budget}]}
    p.update(over)
    return p


def violation_codes(payload) -> tuple[httpx.Response, list[str]]:
    r = c.post("/api/projects/validate", json=payload, headers=officer)
    return r, [v["code"] for v in r.json().get("violations", [])] if r.status_code == 200 else codes(r)


# =============================================================================
# A. ตรวจข้อมูล
# =============================================================================
r = c.post("/api/projects/validate", json=project("500000.00"), headers=officer)
errs = [v["code"] for v in r.json().get("violations", []) if v["severity"] == "ERROR"]
warns = [v["code"] for v in r.json().get("violations", []) if v["severity"] == "WARNING"]
# คำเตือน (เช่น สงสัยแบ่งซื้อเมื่อรันซ้ำ) ยอมรับได้ — ที่ตรวจคือ "ไม่มี ERROR เรื่องวงเงิน"
check(A, "เฉพาะเจาะจง 56(2)(ข) วงเงิน 500,000.00 พอดีเพดาน", "ไม่มี ERROR", r.status_code == 200 and not errs,
      f"HTTP {r.status_code} errors={errs} warnings={warns}")
r, vs = violation_codes(project("500000.01"))
check(A, "เฉพาะเจาะจง 56(2)(ข) วงเงิน 500,000.01 (เกิน 1 สตางค์)", "BUDGET_EXCEEDS_SPECIFIC_LIMIT",
      "BUDGET_EXCEEDS_SPECIFIC_LIMIT" in vs, ",".join(vs))
r, vs = violation_codes(project("500000.00", method_code="E_BIDDING", justification_id=None))
check(A, "e-bidding วงเงิน 500,000 (ต้องเกิน 5 แสน)", "BUDGET_TOO_LOW_FOR_GENERAL_INVITATION",
      "BUDGET_TOO_LOW_FOR_GENERAL_INVITATION" in vs, ",".join(vs))
r, vs = violation_codes(project(justification_id=None))
check(A, "วิธีเฉพาะเจาะจงไม่ระบุเหตุผลมาตรา 56", "422", r.status_code == 422, f"HTTP {r.status_code}")
r, vs = violation_codes(project("100000.00", items=[{"description": "x", "quantity": "3", "unit_th": "ชุด", "unit_price": "33333.34"}]))
check(A, "ยอดรวมรายการ 100,000.02 > วงเงิน 100,000.00", "ITEMS_EXCEED_BUDGET", "ITEMS_EXCEED_BUDGET" in vs, ",".join(vs))
r = c.post("/api/projects/validate", json=project("100000.00", reference_price="120000.00"), headers=officer)
vv = r.json()["violations"]
check(A, "ราคากลางสูงกว่าวงเงิน", "WARNING (ไม่บล็อก)",
      any(v["code"] == "REFERENCE_PRICE_OVER_BUDGET" and v["severity"] == "WARNING" for v in vv),
      ",".join(f"{v['code']}/{v['severity']}" for v in vv))
for label, payload in [("จำนวนเงินทศนิยม 3 ตำแหน่ง", project("150000.005")),
                       ("ชื่อโครงการยาวเกิน 500 ตัวอักษร", project(title_th="ก" * 501)),
                       ("เลขที่โครงการรูปแบบผิด (ตัวเล็ก/เว้นวรรค)", project(project_code="val 1")),
                       ("เลขโครงการ e-GP ไม่ครบ 11 หลัก", project(egp_project_no="12345"))]:
    r = c.post("/api/projects/validate", json=payload, headers=officer)
    check(A, label, "422", r.status_code == 422, f"HTTP {r.status_code}")

for tid, label in [("0105536092642", "checksum ผิด"), ("1234567890121", "นิติบุคคลไม่ขึ้นต้นด้วย 0"), ("010553609264", "12 หลัก")]:
    r = c.post("/api/vendors", headers=officer, json={"tax_id": tid, "vendor_type": "JURISTIC", "name_th": "x", "address_th": "x"})
    check(A, f"เลขผู้เสียภาษี: {label} ({tid})", "422", r.status_code == 422, f"HTTP {r.status_code}")
r = c.post("/api/vendors", headers=officer, json={"tax_id": tax_id("01055" + STAMP + "9"), "vendor_type": "JURISTIC",
                                                  "name_th": "x", "address_th": "x", "phone": "12-345", "bank_account": "abc"})
check(A, "เบอร์โทร/เลขบัญชีรูปแบบผิด", "422", r.status_code == 422,
      f"HTTP {r.status_code} fields={[v['field'] for v in r.json()['violations']]}")

# --- Dynamic Form บนโครงการจริง ------------------------------------------------
r = c.post("/api/projects", headers=officer, json={**project(), "acknowledge_warnings": True})
if r.status_code != 201:
    sys.exit(f"สร้างโครงการทดสอบไม่สำเร็จ: {r.text}")
pid = r.json()["project_id"]
people = [p["personnel_id"] for p in c.get("/api/personnel", headers=officer).json()][:3]
if len(people) < 3:
    sys.exit("ต้องมีบุคลากรที่ใช้งานอยู่อย่างน้อย 3 คน (รัน seed_demo.py)")


def submit(step, data, who=officer):
    v = c.get(f"/api/projects/{pid}", headers=who).json()["row_version"]
    return c.post(f"/api/projects/{pid}/steps/{step}/submit", headers=who, json={"data": data, "row_version": v})


r = submit("PRICE_AGREEMENT", {})
check(A, "ข้ามขั้นตอน: บันทึกตกลงราคาก่อนรายงานขอซื้อ", "PREVIOUS_STEP_PENDING", codes(r) == ["PREVIOUS_STEP_PENDING"], f"{codes(r)}")
good = {"doc_no": "VAL 1/2570", "doc_date": "2026-10-12", "reason_th": "r", "spec_summary": "s", "reference_price": "150000.00",
        "reference_price_source": "4", "delivery_days": 15, "evaluation_criteria": "PRICE", "inspection_committee": people}
for label, data, expect in [
    ("ผู้ตรวจรับคนเดียว วงเงิน 150,000 (> 100,000)", {**good, "inspection_committee": people[:1]}, "SOLE_INSPECTOR_NOT_ALLOWED"),
    ("ส่งเงินเป็น float ใน JSON", {**good, "reference_price": 150000.0}, "INVALID"),
    ("วันที่รูปแบบผิด", {**good, "doc_date": "12/10/2569"}, "INVALID"),
    ("ตัวเลือกที่ไม่มีในรายการ (select)", {**good, "reference_price_source": "9"}, "INVALID"),
    ("ฟิลด์แปลกปลอมในฟอร์ม (mass assignment)", {**good, "approved_by": 1}, "UNKNOWN_FIELDS"),
]:
    r = submit("PURCHASE_REQUEST_REPORT", data)
    check(A, label, expect, expect in codes(r), f"HTTP {r.status_code} {codes(r)}")
r = c.post(f"/api/projects/{pid}/steps/PURCHASE_REQUEST_REPORT/submit", headers=officer, json={"data": good, "row_version": 999})
check(A, "row_version เก่า (มีคนแก้ก่อน)", "409", r.status_code == 409, f"HTTP {r.status_code}")
r = submit("PURCHASE_REQUEST_REPORT", good, who=head)
check(A, "ข้อมูลถูกต้องครบ", "บันทึกได้", r.status_code == 200, f"HTTP {r.status_code} {r.json().get('status')}")

# =============================================================================
# C. ความปลอดภัย / สิทธิ์
# =============================================================================
decide = f"/api/projects/{pid}/steps/PURCHASE_REQUEST_REPORT/decision"
r = c.post(decide, headers=officer, json={"approve": True})
check(C, "เจ้าหน้าที่พัสดุกดอนุมัติ", "403", r.status_code == 403, f"HTTP {r.status_code}")
# นโยบายเริ่มต้น (PROC_SELF_APPROVAL_ROLES): หัวหน้าเจ้าหน้าที่อนุมัติรายการที่ตนเองส่งได้ แต่ต้องมีหลักฐาน self_approval ใน audit
r = c.post(decide, headers=head, json={"approve": True})
check(C, "หัวหน้าอนุมัติรายการที่ตนเองส่ง (นโยบายเริ่มต้นอนุญาต)", "200 APPROVED", r.status_code == 200 and r.json().get("status") == "APPROVED",
      f"HTTP {r.status_code} {r.json().get('status')}")
rows = c.get("/api/admin/audit", headers=admin, params={"limit": 10}).json().get("items", [])
flagged = next((a for a in rows if a.get("action") == "STEP_APPROVE" and (a.get("new_values") or {}).get("self_approval") is True), None)
check(C, "audit log ระบุ self_approval=true เมื่ออนุมัติรายการตนเอง", "มี flag", flagged is not None,
      f"entity={flagged['entity_id']}" if flagged else "ไม่พบแถว STEP_APPROVE ที่มี self_approval=true")
r = c.post(decide, headers=director, json={"approve": True})
check(C, "อนุมัติซ้ำรายการที่อนุมัติแล้ว", "STEP_NOT_SUBMITTED", codes(r) == ["STEP_NOT_SUBMITTED"], f"HTTP {r.status_code} {codes(r)}")
r = c.post("/api/projects", headers=officer, json={**project(project_code=f"VAL-{STAMP}-B"), "status": "COMPLETED"})
check(C, "ส่ง status=COMPLETED ตอนสร้างโครงการ", "422", r.status_code == 422, f"HTTP {r.status_code}")

for path, who, label, exp in [("/api/admin/users", officer, "เจ้าหน้าที่ → รายชื่อผู้ใช้", 403),
                              ("/api/admin/backups", head, "หัวหน้า → ไฟล์สำรอง", 403),
                              ("/api/admin/audit", director, "ผู้บริหาร → Audit Log", 403),
                              ("/api/projects", admin, "ผู้ดูแล → รายการโครงการ (อ่านได้)", 200)]:
    r = c.get(path, headers=who)
    check(C, f"RBAC: {label}", str(exp), r.status_code == exp, f"HTTP {r.status_code}")

# ผู้ประกอบการทดสอบ (มีเบอร์/บัญชี เพื่อตรวจการปิดบัง)
PHONE, BANK = "0812345678", "9876543210"
r = c.post("/api/vendors", headers=officer, json={"tax_id": tax_id("01055" + STAMP + "8"), "vendor_type": "JURISTIC",
                                                  "name_th": f"[ทดสอบความปลอดภัย {STAMP}]", "address_th": "x",
                                                  "phone": PHONE, "bank_account": BANK})
vendor_id = r.json()["vendor_id"]
r = c.post(f"/api/vendors/{vendor_id}/sanctions", headers=officer,
           json={"sanction_type": "SUSPENDED", "reference_no": "xxx", "effective_from": "2026-01-01"})
check(C, "RBAC: เจ้าหน้าที่บันทึกผู้ทิ้งงาน", "403", r.status_code == 403, f"HTTP {r.status_code}")

r = c.get("/api/projects")
check(C, "ไม่มี token", "401", r.status_code == 401, f"HTTP {r.status_code}")
h, p, s = officer["Authorization"][7:].split(".")
payload = json.loads(base64.urlsafe_b64decode(p + "=="))
payload["roles"] = ["ADMIN"]
forged = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
r = c.get("/api/admin/users", headers={"Authorization": f"Bearer {h}.{forged}.{s}"})
check(C, "แก้ payload ใน JWT (ลายเซ็นเดิม)", "401", r.status_code == 401, f"HTTP {r.status_code}")
none_hdr = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').decode().rstrip("=")
r = c.get("/api/admin/users", headers={"Authorization": f"Bearer {none_hdr}.{forged}."})
check(C, "JWT alg=none", "401", r.status_code == 401, f"HTTP {r.status_code}")

all_projects = c.get("/api/projects", headers=officer, params={"limit": 200}).json()
before = len(all_projects)
for q in ["' OR '1'='1", "'; DROP TABLE projects; --", "%", "_"]:
    r = c.get("/api/projects", headers=officer, params={"q": q})
    # ผลค้นหาต้องตรงกับโครงการที่ "มีข้อความนี้จริง" เท่านั้น (ไม่ถูกตีความเป็น SQL/wildcard) — ไม่ขึ้นกับข้อมูลในฐาน
    literal = sorted(p["project_id"] for p in all_projects if q.lower() in (p["title_th"] + p["project_code"]).lower())
    got = sorted(p["project_id"] for p in r.json()) if r.status_code == 200 else None
    check(C, f"SQL injection / wildcard ในช่องค้นหา: {q}", "เฉพาะแถวที่มีข้อความนี้จริง",
          got == literal, f"HTTP {r.status_code}, ได้ {len(got or [])} แถว, มีข้อความนี้จริง {len(literal)} แถว (ทั้งหมด {before})")
after = len(c.get("/api/projects", headers=officer, params={"limit": 200}).json())
check(C, "ตาราง projects ยังอยู่ครบหลังลอง injection", "จำนวนเท่าเดิม", before == after, f"{before} → {after}")
r = c.post("/api/auth/login", json={"username": "admin' --", "password": "x"})
check(C, "SQL injection ในชื่อผู้ใช้ตอน login", "422", r.status_code == 422, f"HTTP {r.status_code}")

r1 = c.post("/api/auth/login", json={"username": f"nobody{STAMP}", "password": "wrong-password"})
r2 = c.post("/api/auth/login", json={"username": USERS["director"], "password": "wrong-password"})
check(C, "กันเดาชื่อผู้ใช้: ข้อความผิดเหมือนกัน", "เหมือนกัน", r1.json() == r2.json() and r1.status_code == r2.status_code == 401,
      f"{r1.json()['message']} | {r2.json()['message']}")

# ผู้ใช้ชั่วคราวสำหรับทดสอบการล็อก (ไม่ไปล็อกบัญชีที่ใช้งานจริง)
temp_user = f"audit{STAMP}"
r = c.post("/api/admin/users", headers=admin, json={
    "username": temp_user, "roles": ["AUDITOR"],
    "personnel": {"department_id": DEPT, "title_th": "นาย", "first_name_th": "ทดสอบ", "last_name_th": f"ล็อก{STAMP}",
                  "position_th": "ทดสอบ", "employment_type": "OTHER", "citizen_id": tax_id("39" + STAMP + "0000")}})
temp_id = r.json()["user"]["user_id"]
for _ in range(5):
    c.post("/api/auth/login", json={"username": temp_user, "password": "wrong-password"})
r = c.post("/api/auth/login", json={"username": temp_user, "password": "wrong-password"})
check(C, "รหัสผิด 5 ครั้ง → ล็อกบัญชี", "423", r.status_code == 423, f"HTTP {r.status_code}: {r.json()['message']}")
c.post(f"/api/admin/users/{temp_id}/unlock", headers=admin)
c.patch(f"/api/admin/users/{temp_id}", headers=admin, json={"is_active": False})   # เก็บกวาด: ระงับบัญชีทดสอบ

hd = c.get("/api/projects", headers=officer).headers
check(C, "Security headers", "CSP, X-Frame-Options, nosniff, no-store",
      bool(hd.get("content-security-policy")) and hd.get("x-frame-options") == "DENY"
      and hd.get("x-content-type-options") == "nosniff" and hd.get("cache-control") == "no-store",
      f"CSP={hd.get('content-security-policy')!r}, XFO={hd.get('x-frame-options')}")

for label, body, exp in [("Path traversal ในชื่อไฟล์กู้คืน", {"file_name": "../../etc/passwd", "password": PW, "confirm_text": "ยืนยันกู้คืนข้อมูล"}, 409),
                         ("กู้คืนด้วยรหัสผ่านผิด", {"file_name": "x", "password": "wrong", "confirm_text": "ยืนยันกู้คืนข้อมูล"}, 403),
                         ("กู้คืนโดยไม่พิมพ์ข้อความยืนยัน", {"file_name": "x", "password": PW, "confirm_text": "ok"}, 422)]:
    r = c.post("/api/admin/restore", headers=admin, json=body)
    check(C, label, str(exp), r.status_code == exp, f"HTTP {r.status_code}")

buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("word/document.xml", "<w:document/>")
    z.writestr("word/vbaProject.bin", b"macro")
form = {"document_type_code": "PURCHASE_ORDER", "version_label": f"v{STAMP}", "cgd_reference": "ทดสอบ", "effective_from": "2026-10-01"}
for label, url, content in [("อัปโหลดแบบฟอร์มที่มี macro", "https://www.gprocurement.go.th/x", buf.getvalue()),
                            ("แหล่งที่มาไม่ใช่ gprocurement.go.th (หลอกด้วย path)", "https://evil.example.com/gprocurement.go.th/x", b"PK\x03\x04junk"),
                            ("ไฟล์ปลอมนามสกุล .docx (ไม่ใช่ OOXML)", "https://www.gprocurement.go.th/x", b"MZ\x90\x00 not office")]:
    r = c.post("/api/admin/templates", headers=admin, data={**form, "source_url": url}, files={"file": ("form.docx", content)})
    check(C, label, "422", r.status_code == 422, f"HTTP {r.status_code}")

v = c.get(f"/api/vendors/{vendor_id}", headers=officer)
check(C, "ข้อมูลผู้ประกอบการ: เบอร์/บัญชีแสดงแบบปิดบัง", "เห็นเฉพาะ 4 หลักท้าย", PHONE not in v.text and BANK not in v.text,
      f"phone={v.json()['phone_masked']}, bank={v.json()['bank_account_masked']}")
pl = c.get("/api/personnel", headers=officer).text
check(C, "API บุคลากรไม่ส่งเลขบัตรประชาชน", "ไม่มีเลข 13 หลัก", not re.search(r"\b\d{13}\b", pl) and "citizen" not in pl,
      "ไม่พบเลข 13 หลักใน response")
me_admin = c.get("/api/auth/me", headers=admin).json()["user_id"]
r = c.patch(f"/api/admin/users/{me_admin}", headers=admin, json={"is_active": False})
check(C, "ผู้ดูแลระงับบัญชีตนเอง", "422", r.status_code == 422, f"HTTP {r.status_code}")
r = c.post("/api/admin/users", headers=admin, json={"username": f"val{STAMP}", "roles": ["AUDITOR", "EXECUTIVE"], "personnel_id": 1})
check(C, "สร้างผู้ใช้บทบาทขัดกัน (ผู้ตรวจสอบ+ผู้บริหาร)", "422", r.status_code == 422, f"HTTP {r.status_code}")

# =============================================================================
# B. ฐานข้อมูล — ทุกข้อ rollback
# =============================================================================
db = psycopg.connect(DB_DSN)


def db_expect_error(sql: str, params=()) -> str:
    try:
        with db.transaction():
            db.execute(sql, params)
        return "ไม่มี error (คำสั่งสำเร็จ!)"
    except psycopg.Error as e:
        return e.diag.message_primary or str(e)


msg = db_expect_error("UPDATE projects SET budget_amount = 600000 WHERE project_id = %s", (pid,))
check(B, "แก้วงเงินตรงใน DB ให้เกินเพดาน 56(2)(ข)", "trigger ปฏิเสธ", "เกินเพดาน" in msg, msg)
# สร้างผู้ประกอบการ 2 รายในทรานแซกชันเดียวกัน (ไม่พึ่งข้อมูลที่มีอยู่ในฐานข้อมูล) แล้วตั้งเป็นผู้ชนะทั้งคู่
msg = db_expect_error("""
    WITH v AS (INSERT INTO vendors (tax_id, vendor_type, name_th, address_th)
               VALUES (%(t1)s, 'JURISTIC', 'tmp1', 'x'), (%(t2)s, 'JURISTIC', 'tmp2', 'x') RETURNING vendor_id)
    INSERT INTO quotations (project_id, vendor_id, quoted_amount, submitted_at, is_winner)
    SELECT %(p)s, vendor_id, 1, now(), true FROM v""",
                      {"p": pid, "t1": tax_id("01055" + STAMP + "5"), "t2": tax_id("01055" + STAMP + "6")})
check(B, "ผู้ชนะ 2 รายในโครงการเดียว", "unique index ปฏิเสธ", "ux_quotations_one_winner" in msg, msg[:90])
msg = db_expect_error("""
    WITH c1 AS (INSERT INTO committees (project_id, committee_type_id)
                SELECT %(p)s, committee_type_id FROM committee_types WHERE code='SELECTION' RETURNING committee_id)
    INSERT INTO committee_members SELECT committee_id, %(per)s, 'CHAIR', 1 FROM c1""", {"p": pid, "per": people[0]})
check(B, "กรรมการตรวจรับเป็นกรรมการคัดเลือกในโครงการเดียวกัน", "trigger ปฏิเสธ", "ไม่ได้" in msg, msg)
msg = db_expect_error("UPDATE audit_logs SET action = 'LOGIN' WHERE audit_id = (SELECT max(audit_id) FROM audit_logs)")
check(B, "แก้ไข audit log", "trigger ปฏิเสธ", "append-only" in msg, msg)
msg = db_expect_error("DELETE FROM audit_logs")
check(B, "ลบ audit log", "trigger ปฏิเสธ", "append-only" in msg, msg)


class _Rollback(Exception):
    pass


mid = broken = None
try:
    with db.transaction():
        mid = db.execute("SELECT audit_id FROM audit_logs ORDER BY audit_id OFFSET 10 LIMIT 1").fetchone()[0]
        db.execute("ALTER TABLE audit_logs DISABLE TRIGGER trg_audit_no_update")
        db.execute("UPDATE audit_logs SET new_values = '{\"edited\": true}' WHERE audit_id = %s", (mid,))
        broken = db.execute("SELECT fn_verify_audit_chain()").fetchone()[0]
        raise _Rollback   # DDL ใน PostgreSQL อยู่ใน transaction → คืนทั้ง trigger และข้อมูล
except _Rollback:
    pass
except psycopg.Error as e:
    broken = f"ทดสอบไม่ได้: {e.diag.message_primary} (ต้องใช้ role ที่เป็นเจ้าของตาราง)"
check(B, f"จำลองปิด trigger แล้วแก้ audit แถว #{mid}", "hash chain ตรวจพบแถวที่ถูกแก้", broken == mid, f"fn_verify_audit_chain() = {broken}")
intact = db.execute("SELECT fn_verify_audit_chain()").fetchone()[0]
enabled = db.execute("SELECT tgenabled FROM pg_trigger WHERE tgname = 'trg_audit_no_update'").fetchone()[0]
check(B, "หลัง rollback: chain สมบูรณ์ + trigger กลับมาทำงาน", "intact, enabled", intact is None and enabled == "O",
      f"first_broken={intact}, tgenabled={enabled}")
r = c.get("/api/admin/audit/verify", headers=admin).json()
check(B, "ตรวจ chain ผ่าน API หลังทดสอบทั้งหมด", "intact", r["intact"], json.dumps(r))

# =============================================================================
os.makedirs(OUT_DIR, exist_ok=True)
with open(os.path.join(OUT_DIR, "results.json"), "w") as f:
    json.dump({"stamp": STAMP, "api": API_URL, "results": results}, f, ensure_ascii=False, indent=1)
failed = [r for r in results if not r["ok"]]
print(f"\nรวม {len(results) - len(failed)}/{len(results)} ผ่าน")
sys.exit(1 if failed else 0)
