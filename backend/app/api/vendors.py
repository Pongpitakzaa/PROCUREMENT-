"""ทะเบียนผู้ประกอบการ + บัญชีผู้ทิ้งงาน.

ข้อมูลติดต่อ/บัญชีธนาคารเก็บแบบเข้ารหัส และ API ส่งออกเฉพาะแบบปิดบัง (data minimization ตาม PDPA)
"""
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import case, exists, func, or_, select
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_field, encrypt_field
from app.core.database import get_db, like_pattern
from app.core.security import Perm, require
from app.models import ProcurementMethod, Project, Quotation, User, Vendor, VendorSanction
from app.rules.validators import clean_text
from app.schemas import SanctionCreate, VendorCreate, VendorUpdate
from app.services.audit_service import write_audit

router = APIRouter(prefix="/api/vendors", tags=["vendors"])
DB = Annotated[Session, Depends(get_db)]


def _active_sanction_clause(today: date):
    """เงื่อนไข 'อยู่ในบัญชีผู้ทิ้งงาน ณ วันนี้' — ใช้ซ้ำทั้งรายการและรายละเอียด."""
    return exists().where(
        VendorSanction.vendor_id == Vendor.vendor_id,
        VendorSanction.effective_from <= today,
        or_(VendorSanction.effective_to.is_(None), VendorSanction.effective_to >= today))


def mask_phone(v: str) -> str:
    return "xxx-xxx-" + v[-4:]


def mask_account(v: str) -> str:
    return "x" * (len(v) - 4) + v[-4:]


@router.get("")
def list_vendors(db: DB, _: Annotated[User, Depends(require(Perm.PROJECT_READ))],
                 q: Annotated[str | None, Query(max_length=100)] = None,
                 vendor_type: Literal["JURISTIC", "INDIVIDUAL"] | None = None,
                 sanctioned: bool | None = None,
                 limit: Annotated[int, Query(ge=1, le=200)] = 100) -> list[dict]:
    """รายการผู้ประกอบการ + สถิติการเสนอราคา (ใช้ทั้งหน้าทะเบียนและช่องค้นหาในฟอร์มเชิญชวน)."""
    today = date.today()
    stats = (select(Quotation.vendor_id,
                    func.count().label("bids"),
                    func.count().filter(Quotation.is_winner).label("wins"),
                    func.coalesce(func.sum(case((Quotation.is_winner,
                                                 func.coalesce(Quotation.agreed_amount, Quotation.quoted_amount)))),
                                  0).label("awarded"))
             .group_by(Quotation.vendor_id).subquery())
    active = _active_sanction_clause(today)
    stmt = (select(Vendor, func.coalesce(stats.c.bids, 0), func.coalesce(stats.c.wins, 0),
                   func.coalesce(stats.c.awarded, 0), active.label("is_sanctioned"))
            .outerjoin(stats, stats.c.vendor_id == Vendor.vendor_id)
            .order_by(Vendor.name_th).limit(limit))
    if q and q.strip():
        text = clean_text(q)
        stmt = stmt.where(or_(Vendor.tax_id == text.replace("-", ""),
                              Vendor.name_th.ilike(like_pattern(text), escape="\\")))
    if vendor_type:
        stmt = stmt.where(Vendor.vendor_type == vendor_type)
    if sanctioned is not None:
        stmt = stmt.where(active if sanctioned else ~active)
    return [{"vendor_id": v.vendor_id, "tax_id": v.tax_id, "vendor_type": v.vendor_type, "name_th": v.name_th,
             "bids": bids, "wins": wins, "awarded_total": awarded, "is_sanctioned": is_sanctioned}
            for v, bids, wins, awarded, is_sanctioned in db.execute(stmt)]


@router.get("/{vendor_id}")
def read_vendor(vendor_id: int, db: DB, _: Annotated[User, Depends(require(Perm.PROJECT_READ))]) -> dict:
    v = db.get(Vendor, vendor_id)
    if v is None:
        raise HTTPException(404, "ไม่พบผู้ประกอบการ")
    today = date.today()
    sanctions = db.scalars(select(VendorSanction).where(VendorSanction.vendor_id == vendor_id)
                           .order_by(VendorSanction.effective_from.desc())).all()
    participation = db.execute(
        select(Project.project_id, Project.project_code, Project.title_th, Project.fiscal_year_be,
               ProcurementMethod.name_th, Quotation.quoted_amount, Quotation.agreed_amount, Quotation.is_winner)
        .join(Project, Project.project_id == Quotation.project_id)
        .join(ProcurementMethod, ProcurementMethod.method_id == Project.method_id)
        .where(Quotation.vendor_id == vendor_id)
        .order_by(Quotation.submitted_at.desc()).limit(50)).all()
    return {
        "vendor_id": v.vendor_id, "tax_id": v.tax_id, "vendor_type": v.vendor_type, "name_th": v.name_th,
        "address_th": v.address_th, "email": v.email,
        # ถอดรหัสเพื่อปิดบังเท่านั้น — ไม่ส่งค่าจริงออกจากเซิร์ฟเวอร์
        "phone_masked": mask_phone(decrypt_field(v.phone_enc, "vendors.phone")) if v.phone_enc else None,
        "bank_account_masked": (mask_account(decrypt_field(v.bank_account_enc, "vendors.bank_account"))
                                if v.bank_account_enc else None),
        "created_at": v.created_at,
        "is_sanctioned": any(s.effective_from <= today and (s.effective_to is None or s.effective_to >= today)
                             for s in sanctions),
        "sanctions": [{"sanction_id": s.sanction_id, "sanction_type": s.sanction_type, "reference_no": s.reference_no,
                       "effective_from": s.effective_from, "effective_to": s.effective_to,
                       "is_active": s.effective_from <= today and (s.effective_to is None or s.effective_to >= today)}
                      for s in sanctions],
        "projects": [{"project_id": r[0], "project_code": r[1], "title_th": r[2], "fiscal_year_be": r[3],
                      "method_name_th": r[4], "quoted_amount": r[5], "agreed_amount": r[6], "is_winner": r[7]}
                     for r in participation],
    }


@router.post("", status_code=201)
def create_vendor(body: VendorCreate, request: Request, db: DB,
                  user: Annotated[User, Depends(require(Perm.VENDOR_WRITE))]) -> dict:
    if db.scalar(select(Vendor.vendor_id).where(Vendor.tax_id == body.tax_id)):
        raise HTTPException(409, "ผู้ประกอบการนี้มีในทะเบียนแล้ว")
    vendor = Vendor(
        tax_id=body.tax_id, vendor_type=body.vendor_type, name_th=body.name_th, address_th=body.address_th,
        email=body.email,
        phone_enc=encrypt_field(body.phone, "vendors.phone") if body.phone else None,
        bank_account_enc=encrypt_field(body.bank_account, "vendors.bank_account") if body.bank_account else None)
    db.add(vendor)
    db.flush()
    write_audit(db, action="CREATE", user_id=user.user_id, request=request, entity_table="vendors",
                entity_id=vendor.vendor_id, new=body.model_dump())   # phone/bank_account ถูก redact
    return {"vendor_id": vendor.vendor_id}


@router.patch("/{vendor_id}")
def update_vendor(vendor_id: int, body: VendorUpdate, request: Request, db: DB,
                  user: Annotated[User, Depends(require(Perm.VENDOR_WRITE))]) -> dict:
    v = db.get(Vendor, vendor_id)
    if v is None:
        raise HTTPException(404, "ไม่พบผู้ประกอบการ")
    changed = body.model_fields_set
    old = {f: getattr(v, f) for f in ("name_th", "address_th", "email") if f in changed}
    for f in ("name_th", "address_th", "email"):
        if f in changed:
            setattr(v, f, getattr(body, f))
    if "phone" in changed:
        v.phone_enc = encrypt_field(body.phone, "vendors.phone") if body.phone else None
    if "bank_account" in changed:
        v.bank_account_enc = encrypt_field(body.bank_account, "vendors.bank_account") if body.bank_account else None
    write_audit(db, action="UPDATE", user_id=user.user_id, request=request, entity_table="vendors",
                entity_id=vendor_id, old=old, new=body.model_dump(include=changed))
    return {"vendor_id": vendor_id}


@router.post("/{vendor_id}/sanctions", status_code=201)
def add_sanction(vendor_id: int, body: SanctionCreate, request: Request, db: DB,
                 user: Annotated[User, Depends(require(Perm.VENDOR_SANCTION))]) -> dict:
    """บันทึกรายชื่อผู้ทิ้งงานตามหนังสือแจ้งเวียน (พ.ร.บ. มาตรา 109) — มีผลห้ามรับเป็นผู้ชนะทันที."""
    if db.get(Vendor, vendor_id) is None:
        raise HTTPException(404, "ไม่พบผู้ประกอบการ")
    s = VendorSanction(vendor_id=vendor_id, **body.model_dump())
    db.add(s)
    db.flush()
    write_audit(db, action="SANCTION", user_id=user.user_id, request=request, entity_table="vendor_sanctions",
                entity_id=s.sanction_id, new={"vendor_id": vendor_id, **body.model_dump()})
    return {"sanction_id": s.sanction_id}

