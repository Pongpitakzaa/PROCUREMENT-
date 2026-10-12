# PROCUREMENT- · ระบบบริหารจัดการและสร้างเอกสารจัดซื้อจัดจ้างภาครัฐ

ต้นแบบ (prototype) Web Application สำหรับงานพัสดุภาครัฐ รองรับ 3 วิธีหลักตาม พ.ร.บ.การจัดซื้อจัดจ้างฯ พ.ศ. 2560 มาตรา 55
(ประกาศเชิญชวนทั่วไป: e-market / e-bidding · คัดเลือก · เฉพาะเจาะจง)

- **Dynamic Workflow** ลำดับขั้นตอนตามวิธีและวงเงินจริง (เช่น e-bidding > 5 ล้านมีขั้นรับฟังความคิดเห็นเพิ่ม)
- **Dynamic Form** ฟอร์มรายขั้นตอนสร้างจาก spec ฝั่ง backend และตรวจด้วยตรรกะเดียวกันทั้ง 2 ฝั่ง
- **CGD Standard Forms Only** ออกเอกสารจากไฟล์แบบฟอร์มกรมบัญชีกลางที่ลงทะเบียนและรับรองแล้วเท่านั้น → **Word / PDF / Excel**
- **LINE Messaging API** แจ้งสถานะ/แชร์ลิงก์เอกสารเข้ากลุ่มงาน (LINE Notify ยุติบริการแล้ว)
- **Dashboard & Report** สรุปยอดรายเดือน/รายวิธี + ส่งออก Excel
- **Backup / Restore** จากหน้าเว็บ (เข้ารหัส AES-256-GCM, ตรวจ checksum, สำรองก่อนกู้อัตโนมัติ)
- **Security** Argon2id, JWT, RBAC + Segregation of Duties, เข้ารหัสข้อมูลส่วนบุคคล, audit log แบบ hash chain

## เอกสารออกแบบ

| # | หัวข้อ | ไฟล์ |
|---|---|---|
| 1 | System Architecture & Workflow | [docs/01-architecture-workflow.md](docs/01-architecture-workflow.md) |
| 2 | Database Schema (3NF) | [docs/02-database-schema.md](docs/02-database-schema.md) · [database/schema.sql](database/schema.sql) |
| 3 | Security & Validation Logic | [docs/03-security-validation.md](docs/03-security-validation.md) |
| 4 | การนำแบบฟอร์มกรมบัญชีกลางเข้าระบบ | [docs/04-cgd-templates.md](docs/04-cgd-templates.md) |

## โค้ดหลักที่ควรอ่าน

| เรื่อง | ไฟล์ |
|---|---|
| กฎระเบียบพัสดุ (rule engine) | `backend/app/rules/procurement_rules.py` |
| Dynamic Form spec + server validation | `backend/app/rules/step_forms.py` |
| Export Word / PDF / Excel | `backend/app/services/export_service.py` |
| แจ้งเตือน LINE | `backend/app/services/line_service.py` · `backend/app/api/documents.py` |
| Backup / Restore | `backend/app/services/backup_service.py` · `backend/app/api/admin.py` |
| Auth / RBAC | `backend/app/core/security.py` |
| Dynamic Form (React) + validation | `frontend/src/components/DynamicStepForm.tsx` · `frontend/src/validation.ts` |

## เริ่มต้นใช้งาน (development)

```bash
# 1) Database
createdb procurement
psql -d procurement -f database/schema.sql -f database/seed.sql

# 2) Backend (ต้องมี pg_dump/pg_restore และ LibreOffice สำหรับ PDF)
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # แล้วสร้าง secret ตามคำแนะนำในไฟล์
uvicorn app.main:app --reload

# 3) Frontend
cd ../frontend && npm install && npm run dev     # http://localhost:5173
```

## การทดสอบ

```bash
cd backend && TEST_DATABASE_URL=postgresql+psycopg://USER:PASS@localhost:5432/procurement_test pytest
cd frontend && npm test && npm run typecheck
```

`backend/tests/test_api_flow.py` ทดสอบครบวงจรบน PostgreSQL จริง: login/lockout → สร้างโครงการ (ตรวจเพดานวงเงิน)
→ workflow วิธีเฉพาะเจาะจงทุกขั้น (บังคับลำดับ, optimistic lock, SoD) → ลงทะเบียน/รับรองแบบฟอร์ม → ส่งออก DOCX/PDF
→ แชร์ LINE + ลิงก์ดาวน์โหลดลงนาม → Dashboard/Excel → ตรวจ audit chain → Backup → Restore
(ทดสอบ test DB จะถูก DROP/CREATE ใหม่ทุกครั้ง — อย่าชี้ไปที่ฐานข้อมูลจริง)

## ข้อจำกัดของต้นแบบ

- **ไม่มีไฟล์แบบฟอร์มกรมบัญชีกลางใน repo** — ต้องดาวน์โหลดจาก gprocurement.go.th และลงทะเบียนตาม docs/04
- ค่าเพดานวงเงินและเลขข้ออ้างอิงระเบียบต้องให้เจ้าหน้าที่พัสดุ/นิติกรทบทวนกับกฎกระทรวงและหนังสือเวียนฉบับล่าสุด
- ระบบนี้ไม่ได้เชื่อมต่อกับระบบ e-GP โดยตรง (ไม่มี API สาธารณะ) — เก็บเลขโครงการ e-GP เพื่ออ้างอิง
- Frontend เป็นตัวอย่างหน้าหลัก (login, workflow, dynamic form) ยังไม่มีหน้า dashboard/admin เต็มรูปแบบ
