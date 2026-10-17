import uuid
from pathlib import Path
from typing import Annotated

import jwt
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import decrypt_field
from app.core.database import get_db
from app.core.security import Perm, require
from app.models import (GeneratedDocument, NotificationChannel, NotificationLog, ProjectStep, User,
                        WorkflowStep)
from app.rules.validators import baht_text
from app.services import line_service
from app.services.audit_service import write_audit
from app.services.export_service import MEDIA_TYPES, export_step_document, sha256_file
from app.api.projects import get_project
from app.schemas import LineShareIn

router = APIRouter(prefix="/api", tags=["documents"])
DB = Annotated[Session, Depends(get_db)]

# สถานะขั้นตอนที่อนุญาตให้ออกเอกสาร: ต้องผ่าน validation ตอน submit แล้วเท่านั้น
EXPORTABLE = {"SUBMITTED", "APPROVED"}


@router.post("/projects/{project_id}/steps/{step_code}/export")
def export_document(project_id: int, step_code: str, request: Request, db: DB, background: BackgroundTasks,
                    user: Annotated[User, Depends(require(Perm.DOCUMENT_EXPORT))],
                    fmt: Annotated[str, Query(alias="format", pattern="^(docx|pdf|xlsx)$")] = "docx") -> FileResponse:
    project = get_project(db, project_id)
    ps = db.scalar(select(ProjectStep).join(WorkflowStep).where(
        ProjectStep.project_id == project_id, WorkflowStep.code == step_code))
    if ps is None:
        raise HTTPException(404, "ไม่พบขั้นตอน")
    if ps.status not in EXPORTABLE:
        raise HTTPException(422, "ต้องบันทึกข้อมูลขั้นตอนนี้ให้ผ่านการตรวจสอบก่อนสร้างเอกสาร")

    result = export_step_document(db, project, ps.step, fmt, user.user_id)
    write_audit(db, action="EXPORT", user_id=user.user_id, request=request, entity_table="generated_documents",
                entity_id=result.document_id, new={"step": step_code, "format": fmt, "sha256": result.sha256})
    # แจ้งกลุ่ม LINE ว่าสร้างเอกสารของขั้นตอนนี้แล้ว (ไม่แนบไฟล์ — ผู้ใช้กดแชร์ลิงก์เองได้จากหน้าโครงการ)
    background.add_task(line_service.notify_step_change, project_id, step_code, "DOCUMENT",
                        user.personnel.full_name_th, user.user_id, detail=f"ไฟล์ {fmt.upper()}")
    return FileResponse(result.path, media_type=result.media_type, filename=result.file_name)


@router.get("/documents/{document_id}/download")
def download_document(document_id: int, request: Request, db: DB,
                      user: Annotated[User, Depends(require(Perm.PROJECT_READ))],
                      token: str | None = None) -> FileResponse:
    """ดาวน์โหลดเอกสารที่สร้างไว้ — ต้อง login เสมอ; token จากลิงก์ LINE ใช้ยืนยันว่าเป็นลิงก์ที่ระบบออกเอง."""
    if token is not None:
        try:
            if line_service.verify_download_token(token) != document_id:
                raise HTTPException(403, "ลิงก์ไม่ถูกต้อง")
        except jwt.PyJWTError:
            raise HTTPException(403, "ลิงก์หมดอายุหรือไม่ถูกต้อง") from None
    doc = db.get(GeneratedDocument, document_id)
    if doc is None:
        raise HTTPException(404, "ไม่พบเอกสาร")
    path = Path(doc.storage_path)
    if not path.is_file() or sha256_file(path) != doc.sha256:
        raise HTTPException(410, "ไฟล์เอกสารไม่ตรงกับที่บันทึกไว้ กรุณาสร้างใหม่")
    write_audit(db, action="DOWNLOAD", user_id=user.user_id, request=request,
                entity_table="generated_documents", entity_id=document_id)
    return FileResponse(path, media_type=MEDIA_TYPES[doc.output_format],
                        filename=f"document-{document_id}.{doc.output_format.lower()}")


@router.post("/projects/{project_id}/share-line")
def share_to_line(project_id: int, body: LineShareIn, request: Request, db: DB,
                  user: Annotated[User, Depends(require(Perm.LINE_SEND))]) -> dict:
    project = get_project(db, project_id)
    channel = db.get(NotificationChannel, body.channel_id)
    if channel is None or not channel.is_active:
        raise HTTPException(404, "ไม่พบกลุ่ม LINE ที่ลงทะเบียนไว้")

    # สถานะล่าสุด = ขั้นตอนล่าสุดที่มีการเคลื่อนไหว
    steps = db.scalars(select(ProjectStep).join(WorkflowStep).where(ProjectStep.project_id == project_id)
                       .order_by(WorkflowStep.step_order)).all()
    latest = next((s for s in reversed(steps) if s.status != "PENDING"), steps[0])

    download_url = None
    status = latest.status
    if body.document_id is not None:
        doc = db.get(GeneratedDocument, body.document_id)
        if doc is None or doc.project_id != project_id:
            raise HTTPException(404, "ไม่พบเอกสารของโครงการนี้")
        token = line_service.create_download_token(doc.document_id, user.user_id)
        download_url = f"{get_settings().public_base_url}/documents/{doc.document_id}?token={token}"
        status = "DOCUMENT"

    message = line_service.build_status_message(
        project_code=project.project_code, project_title=project.title_th, method_name=project.method.name_th,
        step_name=latest.step.name_th, status=status,
        budget_text=f"{project.budget_amount:,.2f} บาท ({baht_text(project.budget_amount)})",
        actor_name=user.personnel.full_name_th, download_url=download_url)

    retry_key = uuid.uuid4()
    to = decrypt_field(channel.line_to_enc, "notification_channels.line_to")
    try:
        http_status = line_service.push_message(to, message, retry_key)
        result = "SENT"
    except line_service.LineSendError as exc:
        http_status, result = None, "FAILED"
        error = str(exc)
    db.add(NotificationLog(channel_id=channel.channel_id, project_id=project_id, retry_key=retry_key,
                           status=result, http_status=http_status, sent_by=user.user_id))
    write_audit(db, action="LINE_SEND", user_id=user.user_id, request=request, entity_table="projects",
                entity_id=project_id, new={"channel_id": channel.channel_id, "status": result,
                                           "document_id": body.document_id})
    if result == "FAILED":
        db.commit()   # เก็บ log ความล้มเหลวไว้ก่อนตอบ error
        raise HTTPException(502, error)
    return {"status": result}
