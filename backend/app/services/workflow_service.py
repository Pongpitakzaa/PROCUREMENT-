"""Workflow engine: สร้าง/บังคับลำดับขั้นตอนตามวิธีจัดหา และผูกผลข้างเคียงของแต่ละขั้นตอน."""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (Committee, CommitteeMember, CommitteeType, Personnel, Project, ProjectStep, Quotation, User, Vendor,
                        VendorSanction, WorkflowStep)
from app.rules import procurement_rules as pr
from app.rules.step_forms import validate_step_data

DONE = {"APPROVED", "SKIPPED"}


class ValidationFailed(Exception):
    def __init__(self, violations: list[pr.RuleViolation]):
        super().__init__("validation failed")
        self.violations = violations


def _fail(code: str, message: str, field: str | None = None, legal_ref: str | None = None) -> ValidationFailed:
    return ValidationFailed([pr.RuleViolation(code, message, field, legal_ref)])


def applicable_steps(db: Session, project: Project) -> list[WorkflowStep]:
    rows = db.scalars(select(WorkflowStep).where(WorkflowStep.method_id == project.method_id)).all()
    defs = {r.code: r for r in rows}
    ordered = pr.applicable_steps(
        [pr.WorkflowStepDef(r.step_order, r.code, r.name_th, r.applies_when_budget_over) for r in rows],
        project.budget_amount)
    return [defs[d.code] for d in ordered]


def init_project_steps(db: Session, project: Project, creator: User) -> None:
    for ws in applicable_steps(db, project):
        auto_done = ws.code == "CREATE_PROJECT"   # ขั้นสร้างโครงการเสร็จเมื่อบันทึกโครงการผ่าน validation
        db.add(ProjectStep(project_id=project.project_id, step_id=ws.step_id,
                           status="APPROVED" if auto_done else "PENDING",
                           submitted_by=creator.user_id if auto_done else None,
                           submitted_at=datetime.now(UTC) if auto_done else None,
                           step_data={}))
    project.status = "IN_PROGRESS"


def _project_steps(db: Session, project: Project) -> dict[str, ProjectStep]:
    return {ps.step.code: ps for ps in db.scalars(
        select(ProjectStep).where(ProjectStep.project_id == project.project_id))}


def _jsonable(data: dict[str, Any]) -> dict[str, Any]:
    """เก็บเงินเป็น string (ไม่ใช่ float) และวันที่เป็น ISO ใน JSONB."""
    return {k: (str(v) if isinstance(v, Decimal) else v.isoformat() if isinstance(v, date) else v)
            for k, v in data.items()}


def submit_step(db: Session, project: Project, step_code: str, raw: dict[str, Any], user: User) -> ProjectStep:
    steps = _project_steps(db, project)
    ordered = [ws.code for ws in applicable_steps(db, project)]
    blocked = pr.can_start_step(ordered, {c for c, ps in steps.items() if ps.status in DONE}, step_code)
    if blocked:
        raise ValidationFailed([blocked])
    ps = steps[step_code]
    if ps.status not in ("PENDING", "IN_PROGRESS", "REJECTED"):
        raise _fail("STEP_LOCKED", "ขั้นตอนนี้ส่งพิจารณาหรืออนุมัติแล้ว แก้ไขไม่ได้")

    clean, violations = validate_step_data(step_code, raw, {"budget_amount": project.budget_amount,
                                                            "method": project.method.code})
    if pr.errors_only(violations):
        raise ValidationFailed(violations)

    _apply_side_effects(db, project, step_code, clean)

    ps.step_data = _jsonable(clean)
    ps.status = "SUBMITTED"
    ps.submitted_by, ps.submitted_at = user.user_id, datetime.now(UTC)
    ps.approved_by = ps.approved_at = None
    return ps


def can_self_approve(user: User) -> bool:
    """บทบาทที่อนุญาตให้อนุมัติรายการของตนเอง (ค่าเริ่มต้น: หัวหน้าเจ้าหน้าที่) — ดู PROC_SELF_APPROVAL_ROLES."""
    from app.core.config import get_settings
    return bool(user.role_codes & set(get_settings().self_approval_roles))


def decide_step(db: Session, project: Project, step_code: str, approve: bool, user: User) -> ProjectStep:
    ps = _project_steps(db, project).get(step_code)
    if ps is None or ps.status != "SUBMITTED":
        raise _fail("STEP_NOT_SUBMITTED", "ขั้นตอนนี้ยังไม่ได้ส่งพิจารณา")
    if ps.submitted_by == user.user_id and not can_self_approve(user):
        # Segregation of Duties: ผู้จัดทำ/เสนอ ต้องไม่ใช่ผู้อนุมัติ (ยกเว้นบทบาทใน PROC_SELF_APPROVAL_ROLES)
        raise _fail("SOD_VIOLATION", "ผู้เสนอไม่สามารถอนุมัติรายการของตนเองได้")
    ps.status = "APPROVED" if approve else "REJECTED"
    ps.approved_by, ps.approved_at = (user.user_id, datetime.now(UTC)) if approve else (None, None)

    if approve:
        ordered = [ws.code for ws in applicable_steps(db, project)]
        if step_code == "AWARD_APPROVAL":
            project.status = "AWARDED"
        if step_code == ordered[-1]:
            project.status = "CONTRACTED" if step_code == "CONTRACT" else "COMPLETED"
    return ps


# ---------------------------------------------------------------------------
# ผลข้างเคียงต่อข้อมูลหลักของแต่ละขั้นตอน
# ---------------------------------------------------------------------------
def _apply_side_effects(db: Session, project: Project, step_code: str, clean: dict[str, Any]) -> None:
    if step_code == "PURCHASE_REQUEST_REPORT":
        project.reference_price = clean["reference_price"]
        project.delivery_days = clean["delivery_days"]
        _replace_committee(db, project, "INSPECTION", clean["inspection_committee"])
    elif step_code == "PRICE_AGREEMENT":
        vendor = _eligible_vendor(db, clean["vendor_tax_id"], "vendor_tax_id")
        q = db.scalar(select(Quotation).where(Quotation.project_id == project.project_id,
                                              Quotation.vendor_id == vendor.vendor_id))
        if q is None:
            q = Quotation(project_id=project.project_id, vendor_id=vendor.vendor_id, submitted_at=datetime.now(UTC))
            db.add(q)
        q.quoted_amount, q.agreed_amount = clean["quoted_amount"], clean["agreed_amount"]
    elif step_code == "AWARD_APPROVAL":
        vendor = _eligible_vendor(db, clean["winner_tax_id"], "winner_tax_id")
        quotes = db.scalars(select(Quotation).where(Quotation.project_id == project.project_id)).all()
        winner = next((q for q in quotes if q.vendor_id == vendor.vendor_id), None)
        if winner is None:
            raise _fail("WINNER_NOT_BIDDER", "ผู้ได้รับคัดเลือกต้องเป็นผู้ที่ยื่นข้อเสนอในโครงการนี้", "winner_tax_id")
        for q in quotes:
            q.is_winner = False
        db.flush()   # ปลดผู้ชนะเดิมก่อน (unique partial index: ผู้ชนะได้ 1 รายต่อโครงการ)
        winner.is_winner = True
        if winner.agreed_amount is None:
            winner.agreed_amount = clean["award_amount"]


def _eligible_vendor(db: Session, tax_id: str, field: str) -> Vendor:
    vendor = db.scalar(select(Vendor).where(Vendor.tax_id == tax_id))
    if vendor is None:
        raise _fail("VENDOR_NOT_FOUND", "ไม่พบผู้ประกอบการในทะเบียน กรุณาลงทะเบียนก่อน", field)
    today = date.today()
    sanctioned = db.scalar(select(VendorSanction.sanction_id).where(
        VendorSanction.vendor_id == vendor.vendor_id, VendorSanction.effective_from <= today,
        (VendorSanction.effective_to.is_(None)) | (VendorSanction.effective_to >= today)))
    if sanctioned:
        raise _fail("VENDOR_SANCTIONED", "ผู้ประกอบการอยู่ในบัญชีรายชื่อผู้ทิ้งงาน", field, "พ.ร.บ. มาตรา 109")
    return vendor


def _replace_committee(db: Session, project: Project, type_code: str, personnel_ids: list[int]) -> None:
    people = {p.personnel_id: p for p in db.scalars(
        select(Personnel).where(Personnel.personnel_id.in_(personnel_ids)))}
    members = [pr.CommitteeMemberFacts(pid, "CHAIR" if i == 0 else "MEMBER",
                                       is_active=pid in people and people[pid].is_active)
               for i, pid in enumerate(personnel_ids)]
    violations = pr.validate_committee(type_code, members, project.budget_amount)
    if pr.errors_only(violations):
        raise ValidationFailed(violations)

    ctype = db.scalar(select(CommitteeType).where(CommitteeType.code == type_code))
    committee = db.scalar(select(Committee).where(Committee.project_id == project.project_id,
                                                  Committee.committee_type_id == ctype.committee_type_id))
    if committee is None:
        committee = Committee(project_id=project.project_id, committee_type_id=ctype.committee_type_id)
        db.add(committee)
    committee.members.clear()
    db.flush()
    sole = len(personnel_ids) == 1
    for i, pid in enumerate(personnel_ids):
        committee.members.append(CommitteeMember(
            personnel_id=pid, seq_no=i + 1,
            member_role="SOLE_INSPECTOR" if sole else ("CHAIR" if i == 0 else "MEMBER")))
    # การตรวจ "กรรมการพิจารณาผลห้ามเป็นกรรมการตรวจรับ" ทำโดย DB trigger trg_committee_conflict
    # และแปลง error เป็น 422 ที่ exception handler
