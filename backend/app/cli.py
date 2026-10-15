"""คำสั่งดูแลระบบสำหรับติดตั้งครั้งแรก/กู้บัญชี — รันในเครื่องเซิร์ฟเวอร์เท่านั้น (ไม่มีทางเรียกผ่านเว็บ)

    python -m app.cli add-department PSD "กองพัสดุ สำนักงาน..."
    python -m app.cli create-admin --username itadmin --department PSD --title นาย --first-name ... \
                                   --last-name ... --position "นักวิชาการคอมพิวเตอร์" --citizen-id 1234567890123
    python -m app.cli reset-password itadmin          # ลืมรหัสผ่าน/บัญชีถูกล็อก
    python -m app.cli list-departments
    python -m app.cli backup --keep-days 30          # สำรองอัตโนมัติ (ตั้ง cron) + ลบไฟล์อัตโนมัติที่เก่ากว่า 30 วัน
    python -m app.cli init-db                         # รันทุกครั้งที่เริ่มคอนเทนเนอร์ (api-entrypoint): สร้าง schema
                                                      # เมื่อฐานข้อมูลว่าง + ปรับโครงสร้างที่ขาด + ผู้ดูแลคนแรกจาก PROC_BOOTSTRAP_*

ใน Docker: docker compose exec api python -m app.cli <คำสั่ง>
รหัสผ่านสุ่มใหม่ทุกครั้งและแสดงบนจอครั้งเดียว — ไม่รับรหัสผ่านทาง argument (จะค้างใน shell history)
ทุกคำสั่งที่เปลี่ยนข้อมูลบันทึก audit log (ผู้กระทำ = NULL หมายถึงผู้ดูแลเซิร์ฟเวอร์)
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.core.crypto import blind_index, encrypt_field
from app.core.database import SessionLocal, engine
from app.core.config import get_settings
from app.core.security import generate_temp_password, hash_password, password_problems
from app.models import Department, Personnel, Role, User, UserRole
from app.rules.validators import clean_text, is_valid_thai_tax_id
from app.services import backup_service
from app.services.audit_service import write_audit


def fail(message: str) -> None:
    sys.exit(f"ผิดพลาด: {message}")


def show_password(username: str, password: str) -> None:
    print(f"\n  ชื่อผู้ใช้ : {username}\n  รหัสผ่าน  : {password}\n")
    print("  แสดงครั้งเดียว — เข้าสู่ระบบแล้วเปลี่ยนรหัสผ่านทันที (เมนูชื่อผู้ใช้ → เปลี่ยนรหัสผ่าน)")


def add_department(args: argparse.Namespace) -> None:
    code, name = args.code.strip().upper(), clean_text(args.name)
    if not code or len(code) > 20 or not name:
        fail("รหัสหน่วยงานยาว 1–20 ตัว และต้องมีชื่อหน่วยงาน")
    with SessionLocal() as db, db.begin():
        if db.scalar(select(Department).where(Department.code == code)):
            fail(f"มีหน่วยงานรหัส {code} แล้ว")
        dept = Department(code=code, name_th=name)
        db.add(dept)
        db.flush()
        write_audit(db, action="CREATE", user_id=None, entity_table="departments", entity_id=dept.department_id,
                    new={"code": code, "name_th": name, "via": "cli"})
    print(f"เพิ่มหน่วยงาน {code} — {name}")


def list_departments(_: argparse.Namespace) -> None:
    with SessionLocal() as db:
        for d in db.scalars(select(Department).order_by(Department.code)):
            print(f"{d.code:<12} {d.name_th}")


def create_admin(args: argparse.Namespace) -> None:
    # เลขประจำตัวประชาชนใช้ checksum เดียวกับเลขผู้เสียภาษี 13 หลัก
    if not re.fullmatch(r"[a-z0-9_.-]{3,60}", args.username):
        fail("ชื่อผู้ใช้ 3–60 ตัว ใช้ a-z 0-9 _ . - เท่านั้น")
    if not is_valid_thai_tax_id(args.citizen_id):
        fail("เลขประจำตัวประชาชนไม่ถูกต้อง (13 หลัก, checksum ไม่ผ่าน)")
    with SessionLocal() as db, db.begin():
        dept = db.scalar(select(Department).where(Department.code == args.department.upper()))
        if dept is None:
            fail(f"ไม่พบหน่วยงานรหัส {args.department} — เพิ่มด้วย add-department ก่อน")
        if db.scalar(select(User).where(User.username == args.username)):
            fail(f"มีชื่อผู้ใช้ {args.username} แล้ว")
        if db.scalar(select(Personnel).where(Personnel.citizen_id_hmac == blind_index(args.citizen_id))):
            fail("มีบุคลากรเลขประจำตัวนี้แล้ว — สร้างบัญชีให้บุคลากรเดิมจากหน้าผู้ดูแลระบบแทน")
        person = Personnel(department_id=dept.department_id, title_th=clean_text(args.title),
                           first_name_th=clean_text(args.first_name), last_name_th=clean_text(args.last_name),
                           position_th=clean_text(args.position), employment_type="CIVIL_SERVANT",
                           citizen_id_enc=encrypt_field(args.citizen_id, "personnel.citizen_id"),
                           citizen_id_hmac=blind_index(args.citizen_id))
        db.add(person)
        db.flush()
        password = generate_temp_password()
        user = User(personnel_id=person.personnel_id, username=args.username, password_hash=hash_password(password),
                    password_changed_at=datetime.now(UTC))
        db.add(user)
        db.flush()
        role = db.scalar(select(Role).where(Role.code == "ADMIN"))
        db.add(UserRole(user_id=user.user_id, role_id=role.role_id))
        write_audit(db, action="CREATE", user_id=None, entity_table="users", entity_id=user.user_id,
                    new={"username": args.username, "roles": ["ADMIN"], "via": "cli"})
    print("สร้างผู้ดูแลระบบแล้ว")
    show_password(args.username, password)


def reset_password(args: argparse.Namespace) -> None:
    with SessionLocal() as db, db.begin():
        user = db.scalar(select(User).where(User.username == args.username))
        if user is None:
            fail(f"ไม่พบผู้ใช้ {args.username}")
        password = generate_temp_password()
        user.password_hash = hash_password(password)
        user.password_changed_at = datetime.now(UTC)   # token เดิมทั้งหมดใช้ไม่ได้ทันที (pwd_ts)
        user.failed_login_count, user.locked_until, user.is_active = 0, None, True
        write_audit(db, action="PASSWORD_RESET", user_id=None, entity_table="users", entity_id=user.user_id,
                    new={"username": args.username, "via": "cli"})
    print("ตั้งรหัสผ่านใหม่และปลดล็อกบัญชีแล้ว")
    show_password(args.username, password)


AUTO_SUFFIX = "-auto"


def backup(args: argparse.Namespace) -> None:
    """สำรองตามรอบเวลา: ไฟล์ชื่อลงท้าย -auto · ลบเฉพาะไฟล์ -auto ที่เก่าเกินกำหนด (ไฟล์ที่ผู้ดูแลสั่งเองไม่ถูกลบ)."""
    try:
        manifest = backup_service.create_backup("system:scheduled", suffix=AUTO_SUFFIX)
    except backup_service.BackupError as exc:
        fail(f"สำรองข้อมูลไม่สำเร็จ: {exc}")
    removed = []
    if args.keep_days:
        cutoff = datetime.now(UTC) - timedelta(days=args.keep_days)
        for m in backup_service.list_backups():
            name = m["file_name"]
            if AUTO_SUFFIX in name and name != manifest["file_name"] and backup_service.snapshot_time(m) < cutoff:
                for f in (get_settings().backup_dir / name, get_settings().backup_dir / f"{name}.json"):
                    f.unlink(missing_ok=True)
                removed.append(name)
    with SessionLocal() as db, db.begin():
        write_audit(db, action="BACKUP", user_id=None, entity_table="backup_jobs", entity_id=manifest["file_name"],
                    new={**manifest, "via": "cli", "pruned": removed})
    print(f"สำรองข้อมูลแล้ว: {manifest['file_name']} ({manifest['size_bytes']:,} bytes)")
    for name in removed:
        print(f"ลบไฟล์สำรองอัตโนมัติที่เก่าเกิน {args.keep_days} วัน: {name}")


# ---------------------------------------------------------------------------
# init-db: ให้ระบบเริ่มเองได้บนแพลตฟอร์มที่ไม่มีขั้นติดตั้ง (เช่น Render) — ปลอดภัยที่จะรันซ้ำทุกครั้ง
# ---------------------------------------------------------------------------
# การปรับโครงสร้างที่ต้องใช้กับฐานข้อมูลที่สร้างจาก schema รุ่นก่อน (ทุกคำสั่งต้องรันซ้ำได้)
MIGRATIONS = [
    "ALTER TABLE document_templates ADD COLUMN IF NOT EXISTS content BYTEA",
    "ALTER TABLE notification_channels ADD COLUMN IF NOT EXISTS line_to_hmac CHAR(64) UNIQUE",
    "ALTER TABLE notification_channels ADD COLUMN IF NOT EXISTS source VARCHAR(10) NOT NULL DEFAULT 'MANUAL'",
    "ALTER TABLE notification_channels ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now()",
]
_INIT_LOCK = 7_300_001   # pg_advisory_lock: กันหลาย instance สร้าง schema พร้อมกัน
_TITLES = ("นางสาว", "นาง", "นาย")


def _schema_dir() -> Path:
    here = Path(__file__).resolve()
    for candidate in (here.parent.parent / "database", here.parent.parent.parent / "database"):   # image / repo
        if (candidate / "schema.sql").is_file():
            return candidate
    raise FileNotFoundError("ไม่พบ database/schema.sql")


def _bootstrap_admin(db) -> str:
    s = get_settings()
    if not s.bootstrap_admin_username:
        return "ไม่ได้ตั้ง PROC_BOOTSTRAP_ADMIN_USERNAME — ข้าม"
    if db.scalar(select(func.count()).select_from(User)):
        return "มีผู้ใช้แล้ว — ข้าม (สร้างผู้ดูแลอัตโนมัติเฉพาะระบบใหม่)"
    username = s.bootstrap_admin_username.strip()
    password = s.bootstrap_admin_password.get_secret_value() if s.bootstrap_admin_password else ""
    citizen_id = (s.bootstrap_admin_citizen_id or "").replace("-", "").strip()
    problems = []
    if not re.fullmatch(r"[a-z0-9_.-]{3,60}", username):
        problems.append("ชื่อผู้ใช้ 3–60 ตัว ใช้ a-z 0-9 _ . - เท่านั้น")
    problems += [f"รหัสผ่าน{p}" for p in password_problems(password, username)]
    if not is_valid_thai_tax_id(citizen_id) or citizen_id.startswith("0"):
        problems.append("เลขประจำตัวประชาชนไม่ถูกต้อง")
    if problems:
        return "สร้างผู้ดูแลไม่ได้: " + " · ".join(problems) + " — แก้ค่า PROC_BOOTSTRAP_* แล้ว deploy ใหม่"

    name = clean_text(s.bootstrap_admin_name or "ผู้ดูแล ระบบ")
    title = next((t for t in _TITLES if name.startswith(t)), "")
    first, _, last = name[len(title):].strip().partition(" ")
    dept = db.scalar(select(Department).order_by(Department.department_id).limit(1))
    if dept is None:
        dept = Department(code="MAIN", name_th=clean_text(s.bootstrap_department_name or "หน่วยงานหลัก"))
        db.add(dept)
        db.flush()
    person = Personnel(department_id=dept.department_id, title_th=title or "-", first_name_th=first or name,
                       last_name_th=last.strip() or "-", position_th="ผู้ดูแลระบบ", employment_type="OTHER",
                       citizen_id_enc=encrypt_field(citizen_id, "personnel.citizen_id"),
                       citizen_id_hmac=blind_index(citizen_id))
    db.add(person)
    db.flush()
    user = User(personnel_id=person.personnel_id, username=username, password_hash=hash_password(password),
                password_changed_at=datetime.now(UTC))
    db.add(user)
    db.flush()
    db.add(UserRole(user_id=user.user_id, role_id=db.scalar(select(Role.role_id).where(Role.code == "ADMIN"))))
    write_audit(db, action="CREATE", user_id=None, entity_table="users", entity_id=user.user_id,
                new={"username": username, "roles": ["ADMIN"], "via": "bootstrap"})
    return f"สร้างผู้ดูแลระบบ {username} แล้ว — เข้าสู่ระบบแล้วเปลี่ยนรหัสผ่าน และลบค่า PROC_BOOTSTRAP_ADMIN_PASSWORD ออกจากการตั้งค่า"


def _backfill_line_hmac(db) -> None:
    """กลุ่ม LINE ที่ลงทะเบียนก่อนมีคอลัมน์ line_to_hmac → คำนวณ blind index ให้ (ต้องใช้กุญแจถอดรหัส จึงทำใน Python)."""
    from app.core.crypto import decrypt_field
    from app.models import NotificationChannel
    for ch in db.scalars(select(NotificationChannel).where(NotificationChannel.line_to_hmac.is_(None))):
        ch.line_to_hmac = blind_index(decrypt_field(ch.line_to_enc, "notification_channels.line_to"))


def init_db(_: argparse.Namespace) -> None:
    raw = engine.raw_connection()   # psycopg ตรง: รัน schema.sql ทั้งไฟล์ (มี function $$...$$) ได้ในครั้งเดียว
    try:
        cur = raw.cursor()
        cur.execute("SELECT pg_advisory_lock(%s)", (_INIT_LOCK,))
        cur.execute("SELECT to_regclass('public.projects') IS NOT NULL")
        if not cur.fetchone()[0]:
            d = _schema_dir()
            cur.execute((d / "schema.sql").read_text(encoding="utf-8"))
            cur.execute((d / "seed.sql").read_text(encoding="utf-8"))
            print("init-db: สร้าง schema และข้อมูลอ้างอิงแล้ว")
        for sql in MIGRATIONS:
            cur.execute(sql)
        raw.commit()
        cur.execute("SELECT pg_advisory_unlock(%s)", (_INIT_LOCK,))
        raw.commit()
    finally:
        raw.close()
    with SessionLocal() as db, db.begin():
        _backfill_line_hmac(db)
        print("init-db:", _bootstrap_admin(db))


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="python -m app.cli", description="คำสั่งดูแลระบบจัดซื้อจัดจ้าง")
    sub = p.add_subparsers(required=True)

    d = sub.add_parser("add-department", help="เพิ่มหน่วยงาน")
    d.add_argument("code")
    d.add_argument("name")
    d.set_defaults(fn=add_department)

    sub.add_parser("list-departments", help="แสดงหน่วยงาน").set_defaults(fn=list_departments)

    a = sub.add_parser("create-admin", help="สร้างบัญชีผู้ดูแลระบบ (ติดตั้งครั้งแรก)")
    a.add_argument("--username", required=True)
    a.add_argument("--department", required=True, help="รหัสหน่วยงาน")
    a.add_argument("--title", required=True, help="คำนำหน้า เช่น นาย นาง นางสาว")
    a.add_argument("--first-name", required=True)
    a.add_argument("--last-name", required=True)
    a.add_argument("--position", required=True)
    a.add_argument("--citizen-id", required=True)
    a.set_defaults(fn=create_admin)

    b = sub.add_parser("backup", help="สำรองข้อมูล (ใช้กับ cron)")
    b.add_argument("--keep-days", type=int, default=0, help="ลบไฟล์สำรองอัตโนมัติที่เก่ากว่า N วัน (0 = ไม่ลบ)")
    b.set_defaults(fn=backup)

    sub.add_parser("init-db", help="สร้าง/ปรับฐานข้อมูลอัตโนมัติ + ผู้ดูแลคนแรก (รันซ้ำได้)").set_defaults(fn=init_db)

    r = sub.add_parser("reset-password", help="ตั้งรหัสผ่านใหม่ + ปลดล็อกบัญชี")
    r.add_argument("username")
    r.set_defaults(fn=reset_password)

    args = p.parse_args(argv)
    try:
        args.fn(args)
    except OperationalError as exc:
        fail(f"เชื่อมต่อฐานข้อมูลไม่ได้ — ตรวจ PROC_DATABASE_URL และสถานะ PostgreSQL ({exc.orig})")


if __name__ == "__main__":
    main()
