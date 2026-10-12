from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db, like_pattern
from app.core.security import Perm, require
from app.models import (Department, MethodJustification, ProcurementMethod, Project, ProjectItem, ProjectStep, User,
                        WorkflowStep)
from app.rules import procurement_rules as pr
from app.rules.step_forms import form_for
from app.rules.validators import clean_text
from app.schemas import ProjectCreate, StepDecisionIn, StepSubmitIn
from app.services import workflow_service as wf
from app.services.audit_service import write_audit

router = APIRouter(prefix="/api", tags=["projects"])
DB = Annotated[Session, Depends(get_db)]


def _violations_out(vs: list[pr.RuleViolation]) -> list[dict]:
    return [{"code": v.code, "message": v.message, "field": v.field, "legal_ref": v.legal_ref,
             "severity": str(v.severity)} for v in vs]


def get_project(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "ไม่พบโครงการ")
    return project


# ---------------------------------------------------------------------------
# ข้อมูลอ้างอิงสำหรับสร้าง Dynamic Workflow/Form ฝั่ง frontend
# ---------------------------------------------------------------------------
@router.get("/methods")
def list_methods(db: DB, _: Annotated[User, Depends(require(Perm.PROJECT_READ))]) -> list[dict]:
    methods = db.scalars(select(ProcurementMethod).order_by(ProcurementMethod.method_id)).all()
    justs = db.scalars(select(MethodJustification)).all()
    return [{
        "code": m.code, "category": m.category, "name_th": m.name_th, "legal_basis": m.legal_basis,
        "min_budget_exclusive": m.min_budget_exclusive, "max_budget_inclusive": m.max_budget_inclusive,
        "justifications": [{"id": j.justification_id, "clause_ref": j.clause_ref,
                            "description_th": j.description_th, "max_budget_inclusive": j.max_budget_inclusive}
                           for j in justs if j.method_id == m.method_id],
    } for m in methods]


@router.get("/workflow/{method_code}")
def workflow_preview(method_code: str, db: DB, _: Annotated[User, Depends(require(Perm.PROJECT_READ))],
                     budget: Annotated[Decimal, Query(gt=0, max_digits=15, decimal_places=2)]) -> list[dict]:
    """ลำดับขั้นตอนที่จะเกิดขึ้นจริงตามวิธี+วงเงิน (เช่น e-bidding > 5 ล้าน มีขั้นรับฟังความคิดเห็น)."""
    rows = db.scalars(select(WorkflowStep).join(ProcurementMethod)
                      .where(ProcurementMethod.code == method_code)).all()
    if not rows:
        raise HTTPException(404, "ไม่พบวิธีจัดหา")
    steps = pr.applicable_steps(
        [pr.WorkflowStepDef(r.step_order, r.code, r.name_th, r.applies_when_budget_over) for r in rows], budget)
    by_code = {r.code: r for r in rows}
    extra = {}
    if method_code == "E_BIDDING":
        extra["min_announce_working_days"] = pr.e_bidding_min_announce_days(budget)
    return [{"order": i + 1, "code": s.code, "name_th": s.name_th, "legal_ref": by_code[s.code].legal_ref,
             "document": by_code[s.code].output_document_type.name_th if by_code[s.code].output_document_type
             else None, **extra} for i, s in enumerate(steps)]


@router.post("/projects/validate")
def validate_project(body: ProjectCreate, db: DB,
                     _: Annotated[User, Depends(require(Perm.PROJECT_WRITE))]) -> dict:
    """Dry-run: frontend เรียกเพื่อแสดงผลตรวจสอบแบบ real-time โดยยังไม่บันทึก."""
    return {"violations": _violations_out(_project_rules(db, body))}


def _project_rules(db: Session, body: ProjectCreate) -> list[pr.RuleViolation]:
    just = db.get(MethodJustification, body.justification_id) if body.justification_id else None
    method = db.scalar(select(ProcurementMethod).where(ProcurementMethod.code == body.method_code))
    if just and just.method_id != method.method_id:
        return [pr.RuleViolation("JUSTIFICATION_MISMATCH", "เหตุผลที่เลือกไม่ตรงกับวิธีจัดหา", "justification_id")]
    items_total = sum((i.quantity * i.unit_price for i in body.items), Decimal("0"))
    violations = pr.validate_method_and_budget(pr.ProjectFacts(
        method=pr.Method(body.method_code), budget_amount=body.budget_amount,
        justification_clause=just.clause_ref if just else None,
        reference_price=body.reference_price, items_total=items_total))

    if body.method_code == "SPECIFIC":
        # ประวัติการจัดซื้อวิธีเฉพาะเจาะจง 30 วันล่าสุดของหน่วยงานเดียวกัน — ตรวจการแบ่งซื้อแบ่งจ้าง
        recent = db.scalars(select(Project).where(
            Project.department_id == body.department_id, Project.method_id == method.method_id,
            Project.procurement_type == body.procurement_type, Project.status != "CANCELLED")).all()
        keyword = body.items[0].description.split()[0]
        history = [pr.PastPurchase(p.department_id, p.procurement_type,
                                   p.items[0].description.split()[0] if p.items else "",
                                   p.budget_amount, p.created_at.date()) for p in recent]
        violations += pr.detect_split_purchase(body.department_id, body.procurement_type, keyword,
                                               body.budget_amount, date.today(), history)
    return violations


@router.post("/projects", status_code=201)
def create_project(body: ProjectCreate, request: Request, db: DB,
                   user: Annotated[User, Depends(require(Perm.PROJECT_WRITE))]) -> dict:
    violations = _project_rules(db, body)
    errors = pr.errors_only(violations)
    warnings = [v for v in violations if v.severity == pr.Severity.WARNING]
    if errors or (warnings and not body.acknowledge_warnings):
        # ส่งคำเตือนกลับให้ผู้ใช้ยืนยันก่อน (เช่น ราคากลางเกินวงเงิน / อาจแบ่งซื้อแบ่งจ้าง)
        raise wf.ValidationFailed(violations)

    method = db.scalar(select(ProcurementMethod).where(ProcurementMethod.code == body.method_code))
    project = Project(
        project_code=body.project_code, egp_project_no=body.egp_project_no, fiscal_year_be=body.fiscal_year_be,
        title_th=body.title_th, reason_th=body.reason_th, department_id=body.department_id,
        method_id=method.method_id, justification_id=body.justification_id,
        procurement_type=body.procurement_type, budget_amount=body.budget_amount,
        reference_price=body.reference_price, delivery_days=body.delivery_days, created_by=user.user_id,
        items=[ProjectItem(line_no=i + 1, **it.model_dump()) for i, it in enumerate(body.items)])
    db.add(project)
    db.flush()   # DB trigger fn_check_project_budget ตรวจซ้ำอีกชั้นที่นี่
    wf.init_project_steps(db, project, user)
    write_audit(db, action="CREATE", user_id=user.user_id, request=request, entity_table="projects",
                entity_id=project.project_id, new=body.model_dump(exclude={"items"}))
    return {"project_id": project.project_id, "warnings": _violations_out(warnings)}


@router.get("/departments")
def list_departments(db: DB, _: Annotated[User, Depends(require(Perm.PROJECT_READ))]) -> list[dict]:
    return [{"department_id": d.department_id, "code": d.code, "name_th": d.name_th}
            for d in db.scalars(select(Department).order_by(Department.name_th))]


ProjectStatus = Literal["DRAFT", "IN_PROGRESS", "AWARDED", "CONTRACTED", "CANCELLED", "COMPLETED"]


@router.get("/projects")
def list_projects(db: DB, _: Annotated[User, Depends(require(Perm.PROJECT_READ))],
                  fiscal_year: Annotated[int | None, Query(ge=2560, le=2700)] = None,
                  status: ProjectStatus | None = None,
                  method: Literal["E_MARKET", "E_BIDDING", "SELECTION", "SPECIFIC"] | None = None,
                  q: Annotated[str | None, Query(max_length=100)] = None,
                  limit: Annotated[int, Query(ge=1, le=200)] = 50) -> list[dict]:
    """รายการโครงการ + ขั้นตอนปัจจุบัน (ขั้นแรกที่ยังไม่อนุมัติ) สำหรับหน้ารายการ."""
    stmt = select(Project).order_by(Project.created_at.desc()).limit(limit)
    if fiscal_year:
        stmt = stmt.where(Project.fiscal_year_be == fiscal_year)
    if status:
        stmt = stmt.where(Project.status == status)
    if method:
        stmt = stmt.join(ProcurementMethod).where(ProcurementMethod.code == method)
    if q and q.strip():
        pattern = like_pattern(clean_text(q))
        stmt = stmt.where(Project.title_th.ilike(pattern, escape="\\")
                          | Project.project_code.ilike(pattern, escape="\\"))
    projects = db.scalars(stmt).unique().all()

    # ขั้นตอนของทุกโครงการในหน้าเดียวดึงครั้งเดียว (ไม่ query ต่อแถว)
    steps_by_project: dict[int, list[ProjectStep]] = {}
    if projects:
        rows = db.scalars(select(ProjectStep).join(WorkflowStep)
                          .where(ProjectStep.project_id.in_([p.project_id for p in projects]))
                          .order_by(ProjectStep.project_id, WorkflowStep.step_order))
        for ps in rows:
            steps_by_project.setdefault(ps.project_id, []).append(ps)

    out = []
    for p in projects:
        steps = steps_by_project.get(p.project_id, [])
        done = sum(s.status in ("APPROVED", "SKIPPED") for s in steps)
        current = next((s for s in steps if s.status not in ("APPROVED", "SKIPPED")), None)
        out.append({
            "project_id": p.project_id, "project_code": p.project_code, "title_th": p.title_th,
            "fiscal_year_be": p.fiscal_year_be, "department_name_th": p.department.name_th,
            "method": {"code": p.method.code, "name_th": p.method.name_th},
            "budget_amount": p.budget_amount, "status": p.status,
            "progress": {"done": done, "total": len(steps)},
            "current_step": ({"code": current.step.code, "name_th": current.step.name_th, "status": current.status}
                             if current else None),
        })
    return out


@router.get("/projects/{project_id}")
def read_project(project_id: int, db: DB, _: Annotated[User, Depends(require(Perm.PROJECT_READ))]) -> dict:
    p = get_project(db, project_id)
    steps = db.scalars(select(ProjectStep).join(WorkflowStep).where(ProjectStep.project_id == project_id)
                       .order_by(WorkflowStep.step_order)).all()
    return {
        "project_id": p.project_id, "project_code": p.project_code, "title_th": p.title_th,
        "method": {"code": p.method.code, "name_th": p.method.name_th}, "status": p.status,
        "budget_amount": p.budget_amount, "reference_price": p.reference_price, "row_version": p.row_version,
        "steps": [{"code": s.step.code, "name_th": s.step.name_th, "legal_ref": s.step.legal_ref,
                   "status": s.status, "has_document": s.step.output_document_type_id is not None}
                  for s in steps],
    }


@router.get("/projects/{project_id}/steps/{step_code}/form")
def step_form(project_id: int, step_code: str, db: DB,
              _: Annotated[User, Depends(require(Perm.PROJECT_READ))]) -> dict:
    """ส่ง FieldSpec ให้ frontend สร้างฟอร์ม + ค่าที่บันทึกไว้ + บริบทที่ใช้ตรวจ (วงเงิน)."""
    p = get_project(db, project_id)
    ps = next((s for s in db.scalars(select(ProjectStep).where(ProjectStep.project_id == project_id))
               if s.step.code == step_code), None)
    if ps is None:
        raise HTTPException(404, "ไม่พบขั้นตอนในโครงการนี้")
    return {"step": {"code": step_code, "name_th": ps.step.name_th, "legal_ref": ps.step.legal_ref,
                     "status": ps.status},
            "fields": [f.model_dump(exclude_none=True) for f in form_for(step_code)],
            "values": ps.step_data,
            "context": {"budget_amount": str(p.budget_amount), "method": p.method.code,
                        "small_purchase_max": str(pr.SMALL_PURCHASE_MAX)},
            "row_version": p.row_version}


@router.post("/projects/{project_id}/steps/{step_code}/submit")
def submit_step(project_id: int, step_code: str, body: StepSubmitIn, request: Request, db: DB,
                user: Annotated[User, Depends(require(Perm.STEP_SUBMIT))]) -> dict:
    p = get_project(db, project_id)
    if p.row_version != body.row_version:
        raise HTTPException(409, "ข้อมูลโครงการถูกแก้ไขโดยผู้อื่น กรุณาโหลดใหม่")
    ps = wf.submit_step(db, p, step_code, body.data, user)
    p.updated_at = datetime.now(UTC)  # แตะ row → row_version +1 (optimistic lock) เมื่อ flush
    write_audit(db, action="STEP_SUBMIT", user_id=user.user_id, request=request, entity_table="project_steps",
                entity_id=f"{project_id}:{step_code}", new=ps.step_data)
    db.flush()
    return {"status": ps.status, "row_version": p.row_version}


@router.post("/projects/{project_id}/steps/{step_code}/decision")
def decide_step(project_id: int, step_code: str, body: StepDecisionIn, request: Request, db: DB,
                user: Annotated[User, Depends(require(Perm.STEP_APPROVE))]) -> dict:
    p = get_project(db, project_id)
    ps = wf.decide_step(db, p, step_code, body.approve, user)
    write_audit(db, action="STEP_APPROVE" if body.approve else "STEP_REJECT", user_id=user.user_id,
                request=request, entity_table="project_steps", entity_id=f"{project_id}:{step_code}",
                new={"comment": body.comment})
    return {"status": ps.status, "project_status": p.status}
