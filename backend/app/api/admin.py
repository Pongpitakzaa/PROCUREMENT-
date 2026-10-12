import hashlib
import io
import json
import re
import uuid
import zipfile
from datetime import UTC, date, datetime
from typing import Annotated

from docxtpl import DocxTemplate
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal, get_db
from app.core.security import Perm, require, verify_password
from app.models import BackupJob, DocumentTemplate, DocumentType, User
from app.schemas import RestoreIn
from app.services import backup_service
from app.services.audit_service import write_audit

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
    write_audit(db, action="RESTORE_REQUESTED", user_id=user.user_id, request=request,
                new={"file_name": body.file_name})
    # สำคัญ: ปิด transaction ของ request นี้ก่อน pg_restore — session ที่โหลด user ไว้ถือ lock ตาราง users
    # ถ้าไม่ปิด DROP TABLE ของ pg_restore จะรอ lock ของเราเอง (deadlock ข้าม process)
    db.commit()
    try:
        result = await run_in_threadpool(backup_service.restore_backup, body.file_name, user.username)
    except backup_service.BackupError as exc:
        raise HTTPException(409, str(exc)) from exc

    # หลัง restore ข้อมูลในตารางเป็นของ ณ เวลาที่สำรอง → บันทึกเหตุการณ์ restore ต่อท้ายใหม่
    with SessionLocal.begin() as db:
        requester = db.scalar(select(User.user_id).where(User.username == user.username))
        db.add(BackupJob(job_type="RESTORE", file_name=body.file_name, status="SUCCESS",
                         requested_by=requester or user.user_id, finished_at=datetime.now(UTC)))
        write_audit(db, action="RESTORE", user_id=requester, request=request, new=result)
    return result


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
