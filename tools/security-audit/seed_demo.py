"""สร้างบัญชีทดสอบ 4 บทบาท (officer/head/admin/director) ในฐานข้อมูลทดสอบ — รันซ้ำได้ (ข้ามบัญชีที่มีแล้ว).

ต้องรันจากโฟลเดอร์ backend พร้อมตัวแปร PROC_* ชุดเดียวกับที่ API ใช้ (เพื่อเข้ารหัสเลขบัตรด้วยกุญแจเดียวกัน):
    cd backend && AUDIT_PASSWORD=... python ../tools/security-audit/seed_demo.py
ฐานข้อมูลต้องรัน database/schema.sql และ seed.sql มาก่อน
"""
import os
import sys

sys.path.insert(0, os.getcwd())                       # ใช้ package app ของ backend
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import psycopg  # noqa: E402

from _guard import DB_DSN, ensure_safe_target, password  # noqa: E402

try:
    from app.core.crypto import blind_index, encrypt_field
    from app.core.security import hash_password
except ImportError:
    sys.exit("รันจากโฟลเดอร์ backend: cd backend && python ../tools/security-audit/seed_demo.py")

ACCOUNTS = [  # username, role, คำนำหน้า, ชื่อ, นามสกุล, ตำแหน่ง, เลขบัตร (ทดสอบ — checksum ถูกต้อง)
    ("officer", "PROCUREMENT_OFFICER", "นาย", "ทดสอบ", "เจ้าหน้าที่", "นักวิชาการพัสดุ", "1100000000016"),
    ("head", "HEAD_OF_PROCUREMENT", "นาง", "ทดสอบ", "หัวหน้า", "หัวหน้าเจ้าหน้าที่", "1100000000024"),
    ("admin", "ADMIN", "นาย", "ทดสอบ", "ผู้ดูแล", "นักวิชาการคอมพิวเตอร์", "1100000000032"),
    ("director", "EXECUTIVE", "นาย", "ทดสอบ", "ผู้บริหาร", "ผู้อำนวยการ", "1100000000059"),
]
# บุคลากรเพิ่มเติม (ไม่มีบัญชี) สำหรับใช้เป็นกรรมการตรวจรับในการทดสอบ
EXTRA_PERSONNEL = [("นางสาว", "ทดสอบ", "กรรมการ", "เจ้าพนักงานพัสดุ", "1100000000041")]


def main() -> None:
    ensure_safe_target()
    pw = password()
    with psycopg.connect(DB_DSN, autocommit=True) as c:
        dept = c.execute("SELECT department_id FROM departments ORDER BY department_id LIMIT 1").fetchone()
        dept_id = dept[0] if dept else c.execute(
            "INSERT INTO departments (code, name_th) VALUES ('TEST', 'หน่วยงานทดสอบ') RETURNING department_id").fetchone()[0]

        def personnel(title, first, last, position, cid) -> int:
            row = c.execute("SELECT personnel_id FROM personnel WHERE citizen_id_hmac = %s", (blind_index(cid),)).fetchone()
            if row:
                return row[0]
            return c.execute("""INSERT INTO personnel (department_id, title_th, first_name_th, last_name_th, position_th,
                                employment_type, citizen_id_enc, citizen_id_hmac)
                                VALUES (%s, %s, %s, %s, %s, 'CIVIL_SERVANT', %s, %s) RETURNING personnel_id""",
                             (dept_id, title, first, last, position, encrypt_field(cid, "personnel.citizen_id"),
                              blind_index(cid))).fetchone()[0]

        for username, role, *person in ACCOUNTS:
            if c.execute("SELECT 1 FROM users WHERE username = %s", (username,)).fetchone():
                print(f"มีแล้ว: {username}")
                continue
            pid = personnel(*person)
            uid = c.execute("INSERT INTO users (personnel_id, username, password_hash) VALUES (%s, %s, %s) RETURNING user_id",
                            (pid, username, hash_password(pw))).fetchone()[0]
            c.execute("INSERT INTO user_roles SELECT %s, role_id FROM roles WHERE code = %s", (uid, role))
            print(f"สร้าง: {username} ({role})")
        for p in EXTRA_PERSONNEL:
            personnel(*p)


if __name__ == "__main__":
    main()
