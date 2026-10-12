"""ทะเบียนบุคลากร / กลุ่ม LINE (ผู้ประกอบการอยู่ที่ app/api/vendors.py)."""
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import StringConstraints
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import encrypt_field
from app.core.database import get_db
from app.core.security import Perm, require
from app.models import NotificationChannel, Personnel, User
from app.schemas import StrictModel
from app.services.audit_service import write_audit

router = APIRouter(prefix="/api", tags=["registry"])
DB = Annotated[Session, Depends(get_db)]


@router.get("/personnel")
def list_personnel(db: DB, _: Annotated[User, Depends(require(Perm.PROJECT_READ))],
                   department_id: int | None = None) -> list[dict]:
    """ใช้ใน dropdown เลือกกรรมการ — ไม่ส่งเลขบัตรประชาชน (data minimization)."""
    stmt = select(Personnel).where(Personnel.is_active.is_(True)).order_by(Personnel.first_name_th)
    if department_id:
        stmt = stmt.where(Personnel.department_id == department_id)
    return [{"personnel_id": p.personnel_id, "full_name_th": p.full_name_th, "position_th": p.position_th}
            for p in db.scalars(stmt)]


class LineChannelIn(StrictModel):
    name_th: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    # groupId/userId ของ LINE: ขึ้นต้น C (กลุ่ม) / U (ผู้ใช้) ตามด้วย hex 32 ตัว
    line_to: Annotated[str, StringConstraints(pattern=r"^[CU][0-9a-f]{32}$")]
    department_id: int | None = None


@router.post("/admin/line-channels", status_code=201)
def create_line_channel(body: LineChannelIn, request: Request, db: DB,
                        user: Annotated[User, Depends(require(Perm.USER_MANAGE))]) -> dict:
    ch = NotificationChannel(name_th=body.name_th, department_id=body.department_id,
                             line_to_enc=encrypt_field(body.line_to, "notification_channels.line_to"))
    db.add(ch)
    db.flush()
    write_audit(db, action="CREATE", user_id=user.user_id, request=request, entity_table="notification_channels",
                entity_id=ch.channel_id, new={"name_th": body.name_th})
    return {"channel_id": ch.channel_id}
