# ทดสอบการตรวจสอบข้อมูลและความปลอดภัย (Security & Validation Audit)

ชุดทดสอบนี้รันกับ**ระบบที่เปิดอยู่จริง** (API + PostgreSQL + หน้าเว็บ) เพื่อยืนยันว่ากฎที่ออกแบบไว้ถูกบังคับใช้จริงทุกชั้น
ต่างจาก unit/integration test ใน `backend/tests` ที่ใช้ TestClient ในโปรเซสเดียวกัน

| กลุ่ม | วิธีทดสอบ | จำนวนข้อ |
|---|---|---|
| A. ตรวจข้อมูล (backend) | ยิงข้อมูลผิดตรงไปที่ API **โดยไม่ผ่านหน้าเว็บ** — พิสูจน์ว่าเซิร์ฟเวอร์ตรวจเอง | 22 |
| B. ฐานข้อมูล (ด่านสุดท้าย) | แก้ข้อมูลตรงใน PostgreSQL ภายใน transaction แล้ว **ROLLBACK ทุกครั้ง** | 9 |
| C. ความปลอดภัย / สิทธิ์ | RBAC, SoD, JWT ปลอม, SQL injection, lockout, path traversal, ไฟล์อันตราย, การปิดบังข้อมูล | 31 |
| D. หน้าเว็บ (เบราว์เซอร์จริง) | XSS, การเก็บ token, การตรวจฝั่ง client ก่อนส่ง | 6 |

## ⚠️ ใช้กับระบบทดสอบเท่านั้น

สคริปต์**สร้างข้อมูลทดสอบ** (โครงการ `VAL-*`/`XSS-*`/`CLI-*`, ผู้ประกอบการ `[ทดสอบ…]`, ผู้ใช้ `audit*` ที่ถูกระงับหลังทดสอบ)
และ**ลองแก้ข้อมูลในฐานข้อมูล** (rollback ทุกครั้ง) — มีด่านกันรันผิดระบบ:

- `AUDIT_API_URL` / `AUDIT_WEB_URL` ต้องเป็น `localhost`
- ชื่อฐานข้อมูลใน `AUDIT_DB_DSN` ต้องมีคำว่า `demo` หรือ `test`

ถ้าไม่ตรงสคริปต์จะหยุดทันที (ข้ามได้ด้วย `AUDIT_ALLOW_UNSAFE_TARGET=1` เมื่อแน่ใจว่าเป็นระบบทดสอบ)

## การตั้งค่า

| ตัวแปร | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `AUDIT_PASSWORD` | — (ต้องตั้ง) | รหัสผ่านของบัญชีทดสอบ `officer` `head` `admin` `director` |
| `AUDIT_API_URL` | `http://localhost:8000` | API |
| `AUDIT_WEB_URL` | `http://localhost:5173` | หน้าเว็บ (กลุ่ม D) |
| `AUDIT_DB_DSN` | `host=localhost dbname=procurement_demo` | psycopg DSN (รหัสผ่านใช้ `PGPASSWORD`/`.pgpass` ได้) |
| `AUDIT_OUT` | `tools/security-audit/out` | ที่เก็บ `results.json`, `report.html`, ภาพหน้าจอ |
| `CHROMIUM_PATH` | — | ใช้ Chromium ของเครื่อง (ไม่ตั้ง = ใช้ของ Playwright: `npx playwright install chromium`) |

ข้อ B "จำลองปิด trigger แล้วแก้ audit" ต้องใช้ role ที่เป็นเจ้าของตาราง `audit_logs` (ถ้าไม่ใช่ ข้อนี้จะรายงานว่าทดสอบไม่ได้)

## วิธีรัน

```bash
# 1) ฐานข้อมูลทดสอบ + บัญชีทดสอบ (ครั้งแรก)
createdb procurement_test
psql -d procurement_test -f database/schema.sql -f database/seed.sql
cd backend                                   # ต้องมีตัวแปร PROC_* ชุดเดียวกับ API (กุญแจเข้ารหัส)
AUDIT_DB_DSN="dbname=procurement_test" AUDIT_PASSWORD='…' python ../tools/security-audit/seed_demo.py

# 2) เปิด API และหน้าเว็บที่ชี้ไปฐานข้อมูลทดสอบ แล้วรันทั้งหมด
cd tools/security-audit
AUDIT_DB_DSN="dbname=procurement_test" AUDIT_PASSWORD='…' ./run.sh            # A+B+C+D → out/report.html
AUDIT_DB_DSN="dbname=procurement_test" AUDIT_PASSWORD='…' ./run.sh --no-browser   # เฉพาะ A+B+C
```

`run.sh` คืนค่า exit code 1 เมื่อมีข้อไม่ผ่าน จึงใช้ใน CI ได้ · รันซ้ำบนฐานข้อมูลเดิมได้ (แต่ละรอบใช้รหัสอ้างอิงไม่ซ้ำกัน)

## ไฟล์

| ไฟล์ | หน้าที่ |
|---|---|
| `_guard.py` | ค่าตั้ง + ด่านกันรันกับระบบจริง |
| `seed_demo.py` | สร้างบัญชีทดสอบ 4 บทบาท + บุคลากรสำหรับเป็นกรรมการ (รันซ้ำได้) |
| `api_db_audit.py` | กลุ่ม A, B, C |
| `browser_audit.mjs` | กลุ่ม D (Playwright) |
| `build_report.py` | สร้าง `out/report.html` จาก `out/results.json` |
| `run.sh` | รันทั้งหมดตามลำดับ |

## การเพิ่มกรณีทดสอบ

เรียก `check(หมวด, ชื่อ, ผลที่คาดหวัง, เงื่อนไขผ่าน, ผลจริง)` — ให้กรณีทดสอบ**สร้างข้อมูลที่ต้องใช้เอง**
และเขียนเงื่อนไขให้ถูกไม่ว่าในฐานข้อมูลจะมีข้อมูลอะไรอยู่ (ตัวอย่าง: การตรวจ SQL injection เทียบผลกับ
"แถวที่มีข้อความนั้นจริง" แทนการคาดว่า "ต้องไม่พบข้อมูล")
