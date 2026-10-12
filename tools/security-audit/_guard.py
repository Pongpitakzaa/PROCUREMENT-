"""ค่าตั้งและด่านกันรันผิดระบบ — ใช้ร่วมกันทุกสคริปต์ในโฟลเดอร์นี้.

สคริปต์ชุดนี้ "สร้างข้อมูลทดสอบ ล็อก/ปลดล็อกบัญชี และลองแก้ข้อมูลในฐานข้อมูล (แล้ว rollback)"
จึงห้ามรันกับระบบจริง: API ต้องเป็น localhost และชื่อฐานข้อมูลต้องมีคำว่า demo/test
เว้นแต่ตั้ง AUDIT_ALLOW_UNSAFE_TARGET=1 อย่างจงใจ
"""
import os
import sys
from urllib.parse import urlparse

API_URL = os.environ.get("AUDIT_API_URL", "http://localhost:8000").rstrip("/")
DB_DSN = os.environ.get("AUDIT_DB_DSN", "host=localhost dbname=procurement_demo")
OUT_DIR = os.environ.get("AUDIT_OUT", os.path.join(os.path.dirname(__file__), "out"))
USERS = {"officer": "officer", "head": "head", "admin": "admin", "director": "director"}


def password() -> str:
    pw = os.environ.get("AUDIT_PASSWORD")
    if not pw:
        sys.exit("ต้องตั้ง AUDIT_PASSWORD (รหัสผ่านของบัญชีทดสอบ officer/head/admin/director)")
    return pw


def ensure_safe_target() -> None:
    if os.environ.get("AUDIT_ALLOW_UNSAFE_TARGET") == "1":
        return
    host = urlparse(API_URL).hostname
    dbname = next((p.split("=", 1)[1] for p in DB_DSN.split() if p.startswith("dbname=")), "")
    problems = []
    if host not in ("localhost", "127.0.0.1", "::1"):
        problems.append(f"AUDIT_API_URL ชี้ไปที่ {host} (ไม่ใช่ localhost)")
    if not any(k in dbname for k in ("demo", "test")):
        problems.append(f"ฐานข้อมูล '{dbname}' ไม่มีคำว่า demo/test")
    if problems:
        sys.exit("หยุด: เป้าหมายอาจเป็นระบบจริง — " + "; ".join(problems)
                 + "\n(ถ้าแน่ใจว่าเป็นระบบทดสอบ ตั้ง AUDIT_ALLOW_UNSAFE_TARGET=1)")
