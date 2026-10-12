import hashlib
import io
import json
import re
import uuid
import zipfile
from pathlib import Path
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from docxtpl import DocxTemplate
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal, get_db
from app.core.security import Perm, require, require_any, verify_password
from app.models import AuditLog, BackupJob, DocumentTemplate, DocumentType, User
from app.schemas import RestoreIn
from app.services import backup_service
from app.services.audit_service import write_audit
from app.services.export_service import sha256_file

router = APIRouter(prefix="/api/admin", tags=["admin"])
DB = Annotated[Session, Depends(get_db)]

CGD_URL = re.compile(r"^https://([a-z0-9-]+\.)*gprocurement\.go\.th/\S+$", re.IGNORECASE)
MAX_TEMPLATE_BYTES = 10 * 1024 * 1024


# ---------------------------------------------------------------------------
# Backup / Restore
# ---------------------------------------------------------------------------
@router.get("/backups")
def list_backups(_: Annotated[User, Depends(require(Perm.BACKUP_RUN))]) -> list[dict]:
    return backup_service.list_backups()


@router.post("/backups", status_code=201)
async def create_backup(request: Request, user: Annotated[User, Depends(require(Perm.BACKUP_RUN))]) -> dict:
    # pg_dump ใช้เวลา → รันใน threadpool ไม่บล็อก event loop; บันทึกสถานะ job ด้วย session แยก
    with SessionLocal.begin() as db:
        job = BackupJob(job_type="BACKUP", file_name="(pending)", status="RUNNING", requested_by=user.user_id)
        db.add(job)
        db.flush()
        job_id = job.backup_job_id
    try:
        manifest = await run_in_threadpool(backup_service.create_backup, user.username)
    except backup_service.BackupError as exc:
        _finish_job(job_id, "FAILED", error=str(exc))
        raise HTTPException(500, "สำรองข้อมูลไม่สำเร็จ") from exc
    _finish_job(job_id, "SUCCESS", manifest=manifest)
    with SessionLocal.begin() as db:
        write_audit(db, action="BACKUP", user_id=user.user_id, request=request, entity_table="backup_jobs",
                    entity_id=job_id, new=manifest)
    return manifest


def _finish_job(job_id: int, status: str, manifest: dict | None = None, error: str | None = None) -> None:
    with SessionLocal.begin() as db:
        job = db.get(BackupJob, job_id)
        job.status, job.finished_at, job.error_message = status, datetime.now(UTC), error
        if manifest:
            job.file_name, job.sha256, job.size_bytes = manifest["file_name"], manifest["sha256"], manifest["size_bytes"]


@router.post("/restore")
async def restore(body: RestoreIn, request: Request, db: DB,
                  user: Annotated[User, Depends(require(Perm.RESTORE_RUN))]) -> dict:
    """กู้คืนข้อมูล: ต้องยืนยันรหัสผ่านซ้ำ + พิมพ์ข้อความยืนยัน (การกระทำที่ย้อนกลับยาก)."""
    if not verify_password(user.password_hash, body.password):
        raise HTTPException(403, "รหัสผ่านไม่ถูกต้อง")
    try:
        since = backup_service.snapshot_time(backup_service.read_manifest(body.file_name))
    except backup_service.BackupError as exc:
        raise HTTPException(409, str(exc)) from exc
    write_audit(db, action="RESTORE_REQUESTED", user_id=user.user_id, request=request,
                new={"file_name": body.file_name})
    db.commit()

    # Audit log ห้ามหายเพราะการกู้คืน: เก็บรายการที่เกิดหลังเวลาสำรองไว้ก่อน แล้วต่อท้าย chain ใหม่หลัง restore
    # (ไม่งั้นผู้มีสิทธิ์ restore จะ "ลบร่องรอย" การกระทำของตนได้ด้วยการสำรองแล้วกู้คืน)
    carried = [{c: getattr(a, c) for c in ("audit_id", "occurred_at", "user_id", "action", "entity_table", "entity_id",
                                         "old_values", "new_values", "ip_address", "user_agent", "request_id",
                                         "row_hash")}
               for a in db.scalars(select(AuditLog).where(AuditLog.occurred_at >= since).order_by(AuditLog.audit_id))]
    # สำคัญ: ปิด transaction ของ request นี้ก่อน pg_restore — session ที่อ่าน users/audit_logs ไว้ถือ lock ตาราง
    # ถ้าไม่ปิด DROP TABLE ของ pg_restore จะรอ lock ของเราเอง (deadlock ข้าม process)
    db.commit()
    try:
        result = await run_in_threadpool(backup_service.restore_backup, body.file_name, user.username)
    except backup_service.BackupError as exc:
        raise HTTPException(409, str(exc)) from exc

    with SessionLocal.begin() as db2:
        users = set(db2.scalars(select(User.user_id)))
        present = set(db2.scalars(select(AuditLog.row_hash)))     # กันซ้ำ: แถวที่อยู่ในไฟล์สำรองอยู่แล้ว
        restored_ids = []
        for r in carried:
            if r["row_hash"] in present:
                continue
            original_id, original_hash = r.pop("audit_id"), r.pop("row_hash")
            if r["user_id"] not in users:      # ผู้ใช้ที่สร้างหลังเวลาสำรองไม่มีในฐานข้อมูลที่กู้คืนแล้ว
                r["user_id"] = None
            db2.add(AuditLog(**r))             # trigger คำนวณ hash ใหม่ต่อท้าย chain → chain ยังตรวจสอบได้
            restored_ids.append({"from_audit_id": original_id, "old_row_hash": original_hash})
        db2.flush()
        requester = db2.scalar(select(User.user_id).where(User.username == user.username))
        if requester is not None:
            db2.add(BackupJob(job_type="RESTORE", file_name=body.file_name, status="SUCCESS",
                              requested_by=requester, finished_at=datetime.now(UTC)))
        write_audit(db2, action="RESTORE", user_id=requester, request=request,
                    new={**result, "username": user.username, "audit_rows_carried_over": restored_ids})
    return {**result, "audit_rows_carried_over": len(restored_ids)}


# ---------------------------------------------------------------------------
# Template Registry — เฉพาะแบบฟอร์มมาตรฐานกรมบัญชีกลาง
# ---------------------------------------------------------------------------
@router.post("/templates", status_code=201)
async def upload_template(
    request: Request, db: DB, user: Annotated[User, Depends(require(Perm.TEMPLATE_MANAGE))],
    document_type_code: Annotated[str, Form(pattern=r"^[A-Z_]{3,50}$")],
    version_label: Annotated[str, Form(max_length=30)],
    source_url: Annotated[str, Form(max_length=500)],
    cgd_reference: Annotated[str, Form(min_length=3, max_length=255)],
    effective_from: Annotated[date, Form()],
    file: Annotated[UploadFile, File()],
    xlsx_variable_schema: Annotated[str | None, Form()] = None,
) -> dict:
    if not CGD_URL.match(source_url):
        raise HTTPException(422, "แหล่งที่มาต้องเป็นเว็บไซต์ gprocurement.go.th ของกรมบัญชีกลางเท่านั้น")
    dtype = db.scalar(select(DocumentType).where(DocumentType.code == document_type_code))
    if dtype is None:
        raise HTTPException(422, "ไม่รู้จักประเภทเอกสาร")

    content = await file.read(MAX_TEMPLATE_BYTES + 1)
    if len(content) > MAX_TEMPLATE_BYTES:
        raise HTTPException(413, "ไฟล์ใหญ่เกิน 10 MB")
    fmt = _detect_office_format(content)

    if fmt == "DOCX":
        # ดึงรายชื่อตัวแปร {{ ... }} จากไฟล์จริง → ใช้ตรวจความครบของข้อมูลตอนสร้างเอกสาร
        variables = sorted(DocxTemplate(io.BytesIO(content)).get_undeclared_template_variables())
        variable_schema = {"variables": variables}
    else:
        try:
            variable_schema = json.loads(xlsx_variable_schema or "")
            assert isinstance(variable_schema, dict) and "cells" in variable_schema
        except (ValueError, AssertionError):
            raise HTTPException(422, "แบบฟอร์ม Excel ต้องระบุ xlsx_variable_schema (ตำแหน่งเซลล์)") from None

    digest = hashlib.sha256(content).hexdigest()
    s = get_settings()
    s.template_dir.mkdir(parents=True, exist_ok=True)
    path = s.template_dir / f"{uuid.uuid4().hex}.{fmt.lower()}"   # ไม่ใช้ชื่อไฟล์จากผู้ใช้
    path.write_bytes(content)

    tpl = DocumentTemplate(document_type_id=dtype.document_type_id, version_label=version_label,
                           source_url=source_url, cgd_reference=cgd_reference, file_format=fmt,
                           storage_path=str(path), sha256=digest, variable_schema=variable_schema,
                           effective_from=effective_from, is_active=False, uploaded_by=user.user_id)
    db.add(tpl)
    db.flush()
    write_audit(db, action="TEMPLATE_UPLOAD", user_id=user.user_id, request=request,
                entity_table="document_templates", entity_id=tpl.template_id,
                new={"source_url": source_url, "sha256": digest, "cgd_reference": cgd_reference})
    return {"template_id": tpl.template_id, "variables": variable_schema, "status": "รอตรวจรับรอง"}


def _detect_office_format(content: bytes) -> str:
    """ตรวจจากเนื้อไฟล์ ไม่เชื่อนามสกุล/Content-Type: ต้องเป็น OOXML zip และไม่มี macro."""
    if not content.startswith(b"PK\x03\x04"):
        raise HTTPException(422, "ไฟล์ต้องเป็น .docx หรือ .xlsx")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            names = set(z.namelist())
            if sum(i.file_size for i in z.infolist()) > 100 * 1024 * 1024:
                raise HTTPException(422, "ไฟล์ขยายตัวผิดปกติ (zip bomb)")
    except zipfile.BadZipFile:
        raise HTTPException(422, "ไฟล์เสียหาย") from None
    if any(n.endswith("vbaProject.bin") for n in names):
        raise HTTPException(422, "ไม่อนุญาตไฟล์ที่มี macro")
    if "word/document.xml" in names:
        return "DOCX"
    if "xl/workbook.xml" in names:
        return "XLSX"
    raise HTTPException(422, "ไฟล์ต้องเป็น .docx หรือ .xlsx")


@router.post("/templates/{template_id}/verify")
def verify_template(template_id: int, request: Request, db: DB,
                    user: Annotated[User, Depends(require(Perm.TEMPLATE_VERIFY))]) -> dict:
    """หัวหน้าเจ้าหน้าที่ตรวจว่าเนื้อหาตรงกับแบบกรมบัญชีกลาง แล้วเปิดใช้ (ผู้ตรวจ ≠ ผู้อัปโหลด)."""
    tpl = db.get(DocumentTemplate, template_id)
    if tpl is None:
        raise HTTPException(404, "ไม่พบแบบฟอร์ม")
    if tpl.uploaded_by == user.user_id:
        raise HTTPException(403, "ผู้อัปโหลดไม่สามารถรับรองแบบฟอร์มของตนเองได้")
    # ปิดฉบับเดิม แล้วเปิดฉบับใหม่ (unique partial index: active ได้ฉบับเดียวต่อประเภทเอกสาร)
    for old in db.scalars(select(DocumentTemplate).where(
            DocumentTemplate.document_type_id == tpl.document_type_id, DocumentTemplate.is_active.is_(True))):
        old.is_active = False
    db.flush()
    tpl.verified_by, tpl.is_active = user.user_id, True
    write_audit(db, action="TEMPLATE_VERIFY", user_id=user.user_id, request=request,
                entity_table="document_templates", entity_id=template_id)
    return {"template_id": template_id, "is_active": True}


@router.get("/audit/verify")
def verify_audit_chain(db: DB, _: Annotated[User, Depends(require(Perm.AUDIT_READ))]) -> dict:
    broken = db.scalar(text("SELECT fn_verify_audit_chain()"))
    return {"intact": broken is None, "first_broken_audit_id": broken}


# ---------------------------------------------------------------------------
# รายการสำหรับหน้าผู้ดูแลระบบ
# ---------------------------------------------------------------------------
TemplateViewer = Annotated[User, Depends(require_any(Perm.TEMPLATE_MANAGE, Perm.TEMPLATE_VERIFY))]


@router.get("/document-types")
def list_document_types(db: DB, _: TemplateViewer) -> list[dict]:
    return [{"code": d.code, "name_th": d.name_th}
            for d in db.scalars(select(DocumentType).order_by(DocumentType.document_type_id))]


@router.get("/templates")
def list_templates(db: DB, _: TemplateViewer) -> list[dict]:
    """ทะเบียนแบบฟอร์ม: ตรวจ SHA-256 ของไฟล์จริงด้วย เพื่อให้เห็นทันทีถ้าไฟล์บน storage ถูกแก้."""
    users = {u.user_id: u.personnel.full_name_th for u in db.scalars(select(User))}
    rows = db.scalars(select(DocumentTemplate).order_by(DocumentTemplate.document_type_id,
                                                        DocumentTemplate.template_id.desc())).all()
    out = []
    for t in rows:
        path = Path(t.storage_path)
        out.append({
            "template_id": t.template_id, "document_type_code": t.document_type.code,
            "document_type_name_th": t.document_type.name_th, "version_label": t.version_label,
            "file_format": t.file_format, "source_url": t.source_url, "cgd_reference": t.cgd_reference,
            "effective_from": t.effective_from, "is_active": t.is_active,
            "status": "ACTIVE" if t.is_active else ("PENDING" if t.verified_by is None else "RETIRED"),
            "variables": t.variable_schema.get("variables", []),
            "uploaded_by": users.get(t.uploaded_by), "verified_by": users.get(t.verified_by),
            "uploaded_by_id": t.uploaded_by,
            "file_ok": path.is_file() and sha256_file(path) == t.sha256,
        })
    return out


@router.get("/audit")
def list_audit(db: DB, _: Annotated[User, Depends(require(Perm.AUDIT_READ))],
               action: Annotated[str | None, Query(pattern=r"^[A-Z_]{2,50}$")] = None,
               username: Annotated[str | None, Query(max_length=60)] = None,
               date_from: date | None = None, date_to: date | None = None,
               before_id: Annotated[int | None, Query(gt=0)] = None,
               limit: Annotated[int, Query(ge=1, le=200)] = 50) -> dict:
    """Audit log แบบแบ่งหน้าด้วย keyset (before_id) — เร็วคงที่แม้ตารางใหญ่ ไม่ใช้ OFFSET."""
    stmt = (select(AuditLog, User.username).outerjoin(User, User.user_id == AuditLog.user_id)
            .order_by(AuditLog.audit_id.desc()).limit(limit + 1))
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if username:
        stmt = stmt.where(User.username == username)
    if date_from:
        stmt = stmt.where(AuditLog.occurred_at >= date_from)
    if date_to:
        stmt = stmt.where(AuditLog.occurred_at < date_to + timedelta(days=1))
    if before_id:
        stmt = stmt.where(AuditLog.audit_id < before_id)
    rows = db.execute(stmt).all()
    page = rows[:limit]
    return {
        "items": [{"audit_id": a.audit_id, "occurred_at": a.occurred_at, "username": uname, "action": a.action,
                   "entity_table": a.entity_table, "entity_id": a.entity_id, "ip_address": a.ip_address,
                   "old_values": a.old_values, "new_values": a.new_values, "row_hash": a.row_hash}
                  for a, uname in page],
        "next_before_id": page[-1][0].audit_id if len(rows) > limit else None,
    }
