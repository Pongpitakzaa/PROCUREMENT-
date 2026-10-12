"""สร้างเอกสารจากแบบฟอร์มมาตรฐานกรมบัญชีกลาง → DOCX / PDF / XLSX.

หลักการ:
1. ใช้เฉพาะ template ที่ลงทะเบียนใน document_templates (source_url ต้องเป็น gprocurement.go.th
   และผ่านการตรวจรับรองโดยหัวหน้าเจ้าหน้าที่) — ไม่มีการ "วาด" แบบฟอร์มเองในโค้ด
2. ตรวจ SHA-256 ของไฟล์ template ทุกครั้งก่อนใช้ กันไฟล์ถูกแก้ไขบน storage
3. ตรวจว่าตัวแปรใน template มีข้อมูลครบก่อน render (ห้ามออกเอกสารที่มีช่องว่าง)
4. render แบบ autoescape → ข้อความผู้ใช้ไม่สามารถฉีด XML/markup เข้าไปในไฟล์ Word ได้
5. เก็บ snapshot ข้อมูลที่ใช้สร้าง (render_context) + hash ไฟล์ผลลัพธ์ไว้เป็นหลักฐาน
"""
from __future__ import annotations

import hashlib
import io
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from docxtpl import DocxTemplate
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (Committee, DocumentTemplate, DocumentType, GeneratedDocument, Project, ProjectStep,
                        WorkflowStep)
from app.rules.validators import baht_text, thai_date


class ExportError(Exception):
    """ข้อผิดพลาดที่แสดงต่อผู้ใช้ได้ (ข้อความภาษาไทย ไม่มีรายละเอียดภายในระบบ)."""


@dataclass(frozen=True)
class ExportResult:
    document_id: int
    file_name: str
    path: Path
    sha256: str
    media_type: str


MEDIA_TYPES = {
    "DOCX": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "PDF": "application/pdf",
    "XLSX": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

ROLE_TH = {"CHAIR": "ประธานกรรมการ", "MEMBER": "กรรมการ",
           "MEMBER_SECRETARY": "กรรมการและเลขานุการ", "SOLE_INSPECTOR": "ผู้ตรวจรับพัสดุ"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _fmt_money(v: Decimal | None) -> str:
    return "" if v is None else f"{v:,.2f}"


# ---------------------------------------------------------------------------
# 1) รวบรวมตัวแปรสำหรับแบบฟอร์ม
# ---------------------------------------------------------------------------
def build_render_context(db: Session, project: Project, step_code: str) -> dict[str, Any]:
    """ชื่อตัวแปรตรงกับ placeholder ใน template ({{ project_title }}, {{ budget_text }} ...).

    คืนค่าเป็นข้อความที่จัดรูปแบบแล้ว (เงินมีจุลภาค, วันที่ไทย, จำนวนเงินตัวอักษร)
    เพื่อให้ template ไม่ต้องมี logic → แบบฟอร์มคงหน้าตาตามต้นฉบับกรมบัญชีกลาง
    """
    steps = {ps.step.code: ps for ps in db.scalars(
        select(ProjectStep).where(ProjectStep.project_id == project.project_id))}
    current = steps.get(step_code)
    data: dict[str, Any] = dict(current.step_data) if current else {}

    committees = db.scalars(select(Committee).where(Committee.project_id == project.project_id)).all()
    committee_ctx = {
        c.committee_type.code.lower(): [
            {"seq": m.seq_no, "name": m.personnel.full_name_th, "position": m.personnel.position_th,
             "role": ROLE_TH[m.member_role]} for m in c.members]
        for c in committees
    }

    items = [{"no": i.line_no, "description": i.description, "quantity": f"{i.quantity:,.2f}",
              "unit": i.unit_th, "unit_price": _fmt_money(i.unit_price), "total": _fmt_money(i.line_total)}
             for i in project.items]
    items_total = sum((i.line_total for i in project.items), Decimal("0"))

    doc_date = date.fromisoformat(data["doc_date"]) if data.get("doc_date") else date.today()
    ctx: dict[str, Any] = {
        "agency_name": project.department.name_th,
        "doc_no": data.get("doc_no", ""),
        "doc_date_th": thai_date(doc_date),
        "project_code": project.project_code,
        "egp_project_no": project.egp_project_no or "",
        "fiscal_year": project.fiscal_year_be,
        "project_title": project.title_th,
        "reason": data.get("reason_th") or project.reason_th,
        "method_name": project.method.name_th,
        "legal_basis": project.method.legal_basis,
        "justification": (f"{project.justification.clause_ref} {project.justification.description_th}"
                          if project.justification else ""),
        "budget_amount": _fmt_money(project.budget_amount),
        "budget_text": baht_text(project.budget_amount),
        "reference_price": _fmt_money(project.reference_price),
        "reference_price_text": baht_text(project.reference_price) if project.reference_price else "",
        "delivery_days": project.delivery_days,
        "items": items,
        "items_total": _fmt_money(items_total),
        "items_total_text": baht_text(items_total),
        "committees": committee_ctx,
    }
    # ข้อมูลเฉพาะขั้นตอน (เช่น ราคาที่ตกลง, เลข PO) — เงินแปลงเป็นข้อความพร้อม baht_text
    for key, value in data.items():
        if key.endswith("_amount") and value not in (None, ""):
            ctx[key] = _fmt_money(Decimal(value))
            ctx[f"{key}_text"] = baht_text(Decimal(value))
        elif key.endswith("_date") and value:
            ctx[f"{key}_th"] = thai_date(date.fromisoformat(value))
        else:
            ctx.setdefault(key, value)
    return ctx


def _active_template(db: Session, document_type_code: str) -> DocumentTemplate:
    tpl = db.scalar(
        select(DocumentTemplate).join(DocumentType)
        .where(DocumentType.code == document_type_code, DocumentTemplate.is_active.is_(True)))
    if tpl is None:
        raise ExportError(f"ยังไม่มีแบบฟอร์มกรมบัญชีกลางที่ผ่านการตรวจรับรองสำหรับเอกสาร {document_type_code}")
    path = Path(tpl.storage_path)
    if not path.is_file() or sha256_file(path) != tpl.sha256:
        # ไฟล์ถูกแก้ไข/เสียหาย → ไม่ออกเอกสาร (integrity check)
        raise ExportError("ไฟล์แบบฟอร์มไม่ตรงกับฉบับที่ตรวจรับรองไว้ กรุณาแจ้งผู้ดูแลระบบ")
    return tpl


# ---------------------------------------------------------------------------
# 2) Renderers
# ---------------------------------------------------------------------------
def render_docx(template_path: Path, context: dict[str, Any]) -> bytes:
    doc = DocxTemplate(str(template_path))
    missing = sorted(v for v in doc.get_undeclared_template_variables() if v not in context)
    if missing:
        raise ExportError(f"ข้อมูลไม่ครบสำหรับแบบฟอร์ม: {', '.join(missing)}")
    doc.render(context, autoescape=True)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def docx_to_pdf(docx_bytes: bytes, timeout_s: int = 90) -> bytes:
    """แปลง DOCX → PDF ด้วย LibreOffice headless (รักษารูปแบบแบบฟอร์มราชการและฟอนต์ TH Sarabun ได้ดีที่สุด).

    - ใช้ profile ชั่วคราวแยกต่อ job → รันขนานได้ ไม่ชนกัน
    - เรียกแบบ list args (ไม่ผ่าน shell) → ไม่มี command injection
    - เซิร์ฟเวอร์ต้องติดตั้งฟอนต์ TH Sarabun New / TH SarabunIT๙ ตามมาตรฐานหนังสือราชการ
    """
    soffice = get_settings().libreoffice_bin
    with tempfile.TemporaryDirectory(prefix="proc-pdf-") as tmp:
        tmpdir = Path(tmp)
        src = tmpdir / "doc.docx"
        src.write_bytes(docx_bytes)
        cmd = [soffice, f"-env:UserInstallation=file://{tmpdir / 'profile'}", "--headless",
               "--convert-to", "pdf", "--outdir", str(tmpdir), str(src)]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=timeout_s)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
            raise ExportError("แปลงไฟล์ PDF ไม่สำเร็จ") from exc
        out = tmpdir / "doc.pdf"
        if not out.is_file():
            raise ExportError("แปลงไฟล์ PDF ไม่สำเร็จ")
        return out.read_bytes()


def render_xlsx(template_path: Path, variable_schema: dict[str, Any], context: dict[str, Any]) -> bytes:
    """เติมข้อมูลลงแบบฟอร์ม Excel ของกรมบัญชีกลาง (เช่น ตารางราคากลาง บก.01–บก.06).

    variable_schema ตัวอย่าง:
      {"cells": {"C3": "project_title", "C4": "agency_name"},
       "table": {"sheet": "บก.01", "start_row": 10,
                 "columns": {"A": "no", "B": "description", "D": "quantity", "E": "unit", "F": "unit_price", "G": "total"}}}
    ตำแหน่งเซลล์กำหนดตอนลงทะเบียน template → ไม่ต้องแก้โค้ดเมื่อกรมบัญชีกลางปรับแบบฟอร์ม
    """
    wb = load_workbook(template_path)
    ws = wb.active
    for cell, var in variable_schema.get("cells", {}).items():
        if var not in context:
            raise ExportError(f"ข้อมูลไม่ครบสำหรับแบบฟอร์ม: {var}")
        ws[cell] = context[var]
    table = variable_schema.get("table")
    if table:
        ws = wb[table["sheet"]] if table.get("sheet") else ws
        for offset, row in enumerate(context.get("items", [])):
            for col, key in table["columns"].items():
                ws[f"{col}{table['start_row'] + offset}"] = row.get(key, "")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 3) Orchestration: เลือก template → ตรวจข้อมูล → render → บันทึกไฟล์ + ประวัติ
# ---------------------------------------------------------------------------
def export_step_document(db: Session, project: Project, step: WorkflowStep, fmt: str, user_id: int) -> ExportResult:
    fmt = fmt.upper()
    if fmt not in MEDIA_TYPES:
        raise ExportError("รูปแบบไฟล์ไม่รองรับ")
    if step.output_document_type is None:
        raise ExportError("ขั้นตอนนี้ไม่มีเอกสารต้องออก")

    tpl = _active_template(db, step.output_document_type.code)
    context = build_render_context(db, project, step.code)

    if tpl.file_format == "DOCX":
        if fmt == "XLSX":
            raise ExportError("แบบฟอร์มนี้เป็นเอกสาร Word ส่งออกเป็น Excel ไม่ได้")
        content = render_docx(Path(tpl.storage_path), context)
        if fmt == "PDF":
            content = docx_to_pdf(content)
    else:
        if fmt != "XLSX":
            raise ExportError("แบบฟอร์มนี้เป็นตาราง Excel ส่งออกได้เฉพาะ .xlsx")
        content = render_xlsx(Path(tpl.storage_path), tpl.variable_schema, context)

    out_dir = get_settings().output_dir / str(project.project_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    # ชื่อไฟล์บน disk ไม่ใช้ข้อความจากผู้ใช้ → กัน path traversal
    stored = out_dir / f"{step.code}-{uuid.uuid4().hex}.{fmt.lower()}"
    stored.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()

    record = GeneratedDocument(
        project_id=project.project_id, template_id=tpl.template_id, document_no=context.get("doc_no") or None,
        output_format=fmt, storage_path=str(stored), sha256=digest, render_context=context,
        generated_by=user_id)
    db.add(record)
    db.flush()
    download_name = f"{project.project_code}_{step.output_document_type.code}.{fmt.lower()}"
    return ExportResult(record.document_id, download_name, stored, digest, MEDIA_TYPES[fmt])


def build_summary_workbook(rows: list[dict[str, Any]], title: str) -> bytes:
    """รายงานสรุปยอดจัดซื้อจัดจ้าง (รายงานภายใน ไม่ใช่แบบฟอร์มกรมบัญชีกลาง จึงสร้างจากโค้ดได้)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "สรุป"
    ws["A1"] = title
    ws["A1"].font = Font(bold=True, size=14)
    headers = ["เดือน", "วิธีจัดหา", "จำนวนโครงการ", "วงเงินงบประมาณ", "ราคาที่จัดซื้อ/จ้าง", "ประหยัดงบ"]
    ws.append([])
    ws.append(headers)
    for c in ws[3]:
        c.font = Font(bold=True)
        c.alignment = Alignment(horizontal="center")
    for r in rows:
        ws.append([r["month"], r["method_name_th"], r["project_count"],
                   float(r["budget_total"]), float(r["award_total"]), float(r["savings_total"])])
    for row in ws.iter_rows(min_row=4, min_col=4, max_col=6):
        for c in row:
            c.number_format = "#,##0.00"
    for col, width in zip("ABCDEF", (12, 45, 14, 20, 20, 16), strict=True):
        ws.column_dimensions[col].width = width
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def libreoffice_available() -> bool:
    return shutil.which(get_settings().libreoffice_bin) is not None
