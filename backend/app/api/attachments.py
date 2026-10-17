"""ไฟล์แนบ PDF ต่อขั้นตอนของโครงการ — อัปโหลด / รายการ / เปิดดูในหน้าเว็บ / ลบ.

ความปลอดภัย:
- รับเฉพาะ PDF จริง (ตรวจ magic bytes ไม่เชื่อนามสกุล) ไม่เกิน 10 MB และไม่เกิน 20 ไฟล์ต่อขั้นตอน
- ปฏิเสธ PDF ที่มี JavaScript / Launch action / auto-action (ลดความเสี่ยงเมื่อเปิดในเบราว์เซอร์)
- เก็บเนื้อหาในฐานข้อมูล (ไม่หายบน Render และติดไปกับการสำรองข้อมูล) · ชื่อไฟล์ถูกตัดเหลือ basename
- เปิดดูต้อง login (frontend ดึงเป็น blob แล้วแสดงใน iframe) · ส่งแบบ inline พร้อม nosniff
"""
import hashlib
import re
from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session, undefer

from app.api.projects import get_project
from app.core.database import get_db
from app.core.security import Perm, permissions_of, require, require_any
from app.models import ProjectStep, StepAttachment, User, WorkflowStep
from app.services.audit_service import write_audit

router = APIRouter(prefix="/api", tags=["attachments"])
DB = Annotated[Session, Depends(get_db)]
MAX_BYTES = 10 * 1024 * 1024
MAX_PER_STEP = 20
_DANGEROUS = re.compile(rb"/(JavaScript|JS|Launch|AA|OpenAction)\b")


def _step(db: Session, project_id: int, step_code: str) -> ProjectStep:
    ps = db.scalar(select(ProjectStep).join(WorkflowStep).where(ProjectStep.project_id == project_id,
                                                                WorkflowStep.code == step_code))
    if ps is None:
        raise HTTPException(404, "ไม่พบขั้นตอนในโครงการนี้")
    return ps


def _safe_name(name: str | None) -> str:
    base = PurePosixPath(PureWindowsPath(name or "").name).name.strip() or "เอกสาร.pdf"
    base = re.sub(r"[\x00-\x1f]", "", base)[:255]
    return base if base.lower().endswith(".pdf") else base[:251] + ".pdf"


def _out(a: StepAttachment) -> dict:
    return {"attachment_id": a.attachment_id, "file_name": a.file_name, "size_bytes": a.size_bytes,
            "sha256": a.sha256, "uploaded_by": a.uploader.personnel.full_name_th, "uploaded_by_id": a.uploaded_by,
            "uploaded_at": a.uploaded_at}


@router.get("/projects/{project_id}/steps/{step_code}/attachments")
def list_attachments(project_id: int, step_code: str, db: DB,
                     _: Annotated[User, Depends(require(Perm.PROJECT_READ))]) -> list[dict]:
    get_project(db, project_id)
    ps = _step(db, project_id, step_code)
    rows = db.scalars(select(StepAttachment).where(StepAttachment.project_id == project_id,
                                                   StepAttachment.step_id == ps.step_id)
                      .order_by(StepAttachment.uploaded_at, StepAttachment.attachment_id))
    return [_out(a) for a in rows]


@router.post("/projects/{project_id}/steps/{step_code}/attachments", status_code=201)
async def upload_attachment(project_id: int, step_code: str, request: Request, db: DB,
                            user: Annotated[User, Depends(require_any(Perm.STEP_SUBMIT, Perm.STEP_APPROVE))],
                            file: Annotated[UploadFile, File()]) -> dict:
    get_project(db, project_id)
    ps = _step(db, project_id, step_code)
    content = await file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise HTTPException(413, "ไฟล์ใหญ่เกิน 10 MB")
    if not content.startswith(b"%PDF-"):
        raise HTTPException(422, "รับเฉพาะไฟล์ PDF เท่านั้น")
    if _DANGEROUS.search(content):
        raise HTTPException(422, "PDF นี้มีสคริปต์หรือคำสั่งเปิดโปรแกรมฝังอยู่ จึงรับไม่ได้ กรุณาบันทึกเป็น PDF ใหม่ (เช่น พิมพ์เป็น PDF)")
    count = db.scalar(select(func.count()).select_from(StepAttachment)
                      .where(StepAttachment.project_id == project_id, StepAttachment.step_id == ps.step_id))
    if count >= MAX_PER_STEP:
        raise HTTPException(422, f"แนบได้ไม่เกิน {MAX_PER_STEP} ไฟล์ต่อขั้นตอน")
    a = StepAttachment(project_id=project_id, step_id=ps.step_id, file_name=_safe_name(file.filename),
                       size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest(), content=content,
                       uploaded_by=user.user_id)
    db.add(a)
    db.flush()
    db.refresh(a)
    write_audit(db, action="ATTACHMENT_UPLOAD", user_id=user.user_id, request=request, entity_table="step_attachments",
                entity_id=a.attachment_id, new={"project_id": project_id, "step": step_code, "file_name": a.file_name,
                                                "size_bytes": a.size_bytes, "sha256": a.sha256})
    return _out(a)


@router.get("/attachments/{attachment_id}")
def view_attachment(attachment_id: int, request: Request, db: DB,
                    user: Annotated[User, Depends(require(Perm.PROJECT_READ))],
                    download: bool = False) -> Response:
    a = db.scalar(select(StepAttachment).options(undefer(StepAttachment.content))
                  .where(StepAttachment.attachment_id == attachment_id))
    if a is None:
        raise HTTPException(404, "ไม่พบไฟล์แนบ")
    if hashlib.sha256(a.content).hexdigest() != a.sha256:
        raise HTTPException(410, "ไฟล์แนบไม่ตรงกับที่บันทึกไว้")
    write_audit(db, action="ATTACHMENT_VIEW", user_id=user.user_id, request=request,
                entity_table="step_attachments", entity_id=attachment_id)
    disposition = "attachment" if download else "inline"
    return Response(a.content, media_type="application/pdf", headers={
        "Content-Disposition": f"{disposition}; filename=\"attachment-{attachment_id}.pdf\"; "
                               f"filename*=UTF-8''{quote(a.file_name)}",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; object-src 'none'; script-src 'none'",
        "Cache-Control": "private, no-store",
    })


@router.delete("/attachments/{attachment_id}", status_code=204)
def delete_attachment(attachment_id: int, request: Request, db: DB,
                      user: Annotated[User, Depends(require_any(Perm.STEP_SUBMIT, Perm.STEP_APPROVE))]) -> Response:
    """ลบได้โดยผู้อัปโหลดเอง หรือผู้มีสิทธิ์อนุมัติ — บันทึก audit (sha256 คงอยู่ในประวัติ)."""
    a = db.get(StepAttachment, attachment_id)
    if a is None:
        raise HTTPException(404, "ไม่พบไฟล์แนบ")
    if a.uploaded_by != user.user_id and Perm.STEP_APPROVE not in permissions_of(user.role_codes):
        raise HTTPException(403, "ลบได้เฉพาะผู้ที่แนบไฟล์เอง หรือผู้มีสิทธิ์อนุมัติ")
    write_audit(db, action="ATTACHMENT_DELETE", user_id=user.user_id, request=request, entity_table="step_attachments",
                entity_id=attachment_id, old={"project_id": a.project_id, "step": a.step.code, "file_name": a.file_name,
                                              "sha256": a.sha256})
    db.delete(a)
    return Response(status_code=204)
