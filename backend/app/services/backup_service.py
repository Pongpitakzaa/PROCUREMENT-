"""สำรองข้อมูล (Backup) และกู้คืน (Restore) PostgreSQL จากหน้าเว็บโดยผู้ดูแลระบบ.

ขั้นตอน Backup:  pg_dump -Fc → เข้ารหัส AES-256-GCM แบบแบ่ง chunk → เขียน manifest (SHA-256)
ขั้นตอน Restore: ตรวจชื่อไฟล์ → ตรวจ SHA-256 กับ manifest → สำรองอัตโนมัติก่อนกู้ (safety backup)
                → ถอดรหัส (ตรวจ auth tag ทุก chunk) → pg_restore --single-transaction

ทำไมต้องมี manifest แยกไฟล์: การ restore จะเขียนทับตาราง backup_jobs ในฐานข้อมูล
จึงต้องมีแหล่งข้อมูลยืนยันความถูกต้องที่อยู่นอกฐานข้อมูล

ข้อแนะนำ Production: ใช้ร่วมกับ backup ระดับ infrastructure (WAL archiving/PITR หรือ managed snapshot)
และคัดลอกไฟล์ไปเก็บนอกสถานที่ (หลัก 3-2-1) — ปุ่มบนเว็บนี้เป็น logical backup สำหรับงานประจำวัน
"""
from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import re
import struct
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.engine import make_url

from app.core.config import get_settings

MAGIC = b"PROCBK1\n"
CHUNK = 4 * 1024 * 1024
BACKUP_NAME = re.compile(r"^procurement-\d{8}T\d{6}(-pre-restore)?\.dump\.enc$")   # whitelist ชื่อไฟล์


class BackupError(Exception):
    pass


# ---------------------------------------------------------------------------
# Streaming authenticated encryption
# ---------------------------------------------------------------------------
def _cipher() -> AESGCM:
    key = base64.b64decode(get_settings().backup_key.get_secret_value())
    if len(key) != 32:
        raise BackupError("backup_key ต้องยาว 32 bytes")
    return AESGCM(key)


def encrypt_stream(src: BinaryIO, dst: BinaryIO) -> None:
    """รูปแบบ: MAGIC | prefix(8) | { final(1) | len(4) | ciphertext+tag } ...

    nonce = prefix || counter  (ไม่ซ้ำภายในไฟล์ และ prefix สุ่มใหม่ทุกไฟล์)
    AAD   = MAGIC || counter || final → สลับลำดับ chunk / ตัดท้ายไฟล์ / แก้ flag จะถอดรหัสไม่ผ่าน
    """
    aes, prefix = _cipher(), os.urandom(8)
    dst.write(MAGIC + prefix)
    counter = 0
    buf = src.read(CHUNK)
    while True:
        nxt = src.read(CHUNK)
        final = 0 if nxt else 1
        aad = MAGIC + struct.pack(">IB", counter, final)
        ct = aes.encrypt(prefix + struct.pack(">I", counter), buf, aad)
        dst.write(struct.pack(">BI", final, len(ct)) + ct)
        if final:
            return
        buf, counter = nxt, counter + 1


def decrypt_stream(src: BinaryIO, dst: BinaryIO) -> None:
    aes = _cipher()
    if src.read(len(MAGIC)) != MAGIC:
        raise BackupError("ไม่ใช่ไฟล์สำรองของระบบนี้")
    prefix = src.read(8)
    counter = 0
    while True:
        header = src.read(5)
        if len(header) != 5:
            raise BackupError("ไฟล์สำรองไม่สมบูรณ์ (ถูกตัดท้าย)")
        final, length = struct.unpack(">BI", header)
        ct = src.read(length)
        aad = MAGIC + struct.pack(">IB", counter, final)
        try:
            dst.write(aes.decrypt(prefix + struct.pack(">I", counter), ct, aad))
        except Exception as exc:  # InvalidTag
            raise BackupError("ไฟล์สำรองถูกแก้ไขหรือกุญแจไม่ถูกต้อง") from exc
        if final:
            if src.read(1):
                raise BackupError("พบข้อมูลแปลกปลอมต่อท้ายไฟล์สำรอง")
            return
        counter += 1


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _pg_env_and_args() -> tuple[dict[str, str], list[str], str]:
    """แยก connection จาก DATABASE_URL; รหัสผ่านส่งผ่าน env PGPASSWORD (ไม่โผล่ใน process list)."""
    url = make_url(str(get_settings().database_url))
    env = {**os.environ, "PGPASSWORD": url.password or ""}
    args = ["-h", url.host or "localhost", "-p", str(url.port or 5432), "-U", url.username or "postgres"]
    return env, args, url.database or ""


@contextmanager
def _exclusive_lock() -> Iterator[None]:
    """กัน backup/restore ทำงานซ้อนกัน (ทั้งข้าม worker process)."""
    d = get_settings().backup_dir
    d.mkdir(parents=True, exist_ok=True)
    with open(d / ".lock", "w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BackupError("มีงานสำรอง/กู้คืนข้อมูลกำลังทำงานอยู่") from None
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_backup_path(file_name: str) -> Path:
    if not BACKUP_NAME.fullmatch(file_name):
        raise BackupError("ชื่อไฟล์สำรองไม่ถูกต้อง")
    path = (get_settings().backup_dir / file_name).resolve()
    if path.parent != get_settings().backup_dir.resolve() or not path.is_file():
        raise BackupError("ไม่พบไฟล์สำรอง")
    return path


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def create_backup(requested_by: str, suffix: str = "", _locked: bool = False) -> dict:
    if not _locked:
        with _exclusive_lock():
            return create_backup(requested_by, suffix, _locked=True)

    s = get_settings()
    env, conn_args, dbname = _pg_env_and_args()
    # เวลาก่อนเริ่ม pg_dump: ทุกอย่างที่ commit หลังจากนี้อาจไม่อยู่ในไฟล์ → ใช้ตอน restore เพื่อยก audit log ต่อ
    snapshot_at = datetime.now(UTC)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    out = s.backup_dir / f"procurement-{stamp}{suffix}.dump.enc"

    with tempfile.NamedTemporaryFile(dir=s.backup_dir, suffix=".dump") as plain:
        cmd = [str(s.pg_bin_dir / "pg_dump"), *conn_args, "-Fc", "--no-owner", "--no-privileges",
               "-f", plain.name, dbname]
        proc = subprocess.run(cmd, env=env, capture_output=True, timeout=3600)
        if proc.returncode != 0:
            raise BackupError("pg_dump ล้มเหลว: " + proc.stderr.decode(errors="replace")[-500:])
        tmp_out = out.with_suffix(".partial")
        with open(plain.name, "rb") as src, open(tmp_out, "wb") as dst:
            encrypt_stream(src, dst)
            dst.flush()
            os.fsync(dst.fileno())
        tmp_out.rename(out)   # atomic: ไม่มีไฟล์ครึ่ง ๆ ที่ดูเหมือนสมบูรณ์

    manifest = {"file_name": out.name, "sha256": _sha256(out), "size_bytes": out.stat().st_size,
                "created_at": datetime.now().isoformat(timespec="seconds"), "snapshot_at": snapshot_at.isoformat(),
                "requested_by": requested_by,
                "format": "pg_dump-custom+aes256gcm-chunked/v1"}
    out.with_name(out.name + ".json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    out.chmod(0o600)
    return manifest


def list_backups() -> list[dict]:
    d = get_settings().backup_dir
    if not d.is_dir():
        return []
    items = [json.loads(p.read_text()) for p in d.glob("procurement-*.dump.enc.json")]
    return sorted(items, key=lambda m: m["created_at"], reverse=True)


def read_manifest(file_name: str) -> dict:
    path = _safe_backup_path(file_name)
    manifest_path = path.with_name(path.name + ".json")
    if not manifest_path.is_file():
        raise BackupError("ไม่พบ manifest ของไฟล์สำรอง")
    return json.loads(manifest_path.read_text())


def snapshot_time(manifest: dict) -> datetime:
    """เวลาที่ข้อมูลในไฟล์สำรองเป็นปัจจุบัน (ไฟล์รุ่นเก่าไม่มี snapshot_at → ใช้ created_at เวลาท้องถิ่นแบบประมาณ)."""
    if manifest.get("snapshot_at"):
        return datetime.fromisoformat(manifest["snapshot_at"])
    return datetime.fromisoformat(manifest["created_at"]).astimezone()


def restore_backup(file_name: str, requested_by: str) -> dict:
    """กู้คืนแบบ all-or-nothing (--single-transaction): ถ้าผิดพลาดกลางทาง ฐานข้อมูลคงสภาพเดิม."""
    with _exclusive_lock():
        path = _safe_backup_path(file_name)
        manifest = read_manifest(file_name)
        if _sha256(path) != manifest["sha256"]:
            raise BackupError("checksum ไม่ตรง — ไฟล์สำรองอาจถูกแก้ไข ยกเลิกการกู้คืน")

        # สำรองสถานะปัจจุบันก่อนเสมอ เผื่อกู้ผิดไฟล์จะย้อนกลับได้
        safety = create_backup(requested_by, suffix="-pre-restore", _locked=True)

        s = get_settings()
        env, conn_args, dbname = _pg_env_and_args()
        with tempfile.NamedTemporaryFile(dir=s.backup_dir, suffix=".dump") as plain:
            with open(path, "rb") as src, open(plain.name, "wb") as dst:
                decrypt_stream(src, dst)
            cmd = [str(s.pg_bin_dir / "pg_restore"), *conn_args, "-d", dbname, "--clean", "--if-exists",
                   "--no-owner", "--no-privileges", "--single-transaction", "--exit-on-error", plain.name]
            proc = subprocess.run(cmd, env=env, capture_output=True, timeout=3600)
            if proc.returncode != 0:
                raise BackupError("pg_restore ล้มเหลว (ฐานข้อมูลไม่ถูกเปลี่ยนแปลง): "
                                  + proc.stderr.decode(errors="replace")[-500:])
        return {"restored": file_name, "safety_backup": safety["file_name"]}
