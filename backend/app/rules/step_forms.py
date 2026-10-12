"""Dynamic Form definitions — "แหล่งความจริงเดียว" ของฟอร์มแต่ละขั้นตอน.

Backend ส่ง FieldSpec เป็น JSON ให้ Frontend สร้างฟอร์มอัตโนมัติ และใช้ spec ชุดเดียวกัน
ตรวจซ้ำฝั่งเซิร์ฟเวอร์ (ไม่เชื่อข้อมูลจาก client เด็ดขาด) → กฎไม่หลุดซิงก์ระหว่าง 2 ฝั่ง
ชื่อตัวแปร (name) ตั้งให้ตรงกับช่องข้อมูลในแบบฟอร์มมาตรฐานกรมบัญชีกลาง เพื่อ map เข้า template ได้ตรง
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel

from app.rules import procurement_rules as pr
from app.rules.validators import clean_text, is_valid_thai_tax_id

FieldType = Literal["text", "textarea", "money", "percent", "integer", "date",
                    "select", "checkbox", "tax_id", "personnel_multi", "vendor_multi"]


class ShowIf(BaseModel):
    field: str
    equals: Any


class FieldSpec(BaseModel):
    name: str
    label_th: str
    type: FieldType
    required: bool = True
    min: float | None = None
    max: float | None = None
    max_length: int | None = None
    min_items: int | None = None
    options: list[dict[str, str]] | None = None
    lte_field: str | None = None          # ค่าต้อง <= ค่าของอีกช่อง (เช่น ราคาตกลง <= ราคาเสนอ)
    show_if: ShowIf | None = None          # แสดง/บังคับกรอกเมื่อเงื่อนไขเป็นจริง
    help_th: str | None = None             # อ้างอิงระเบียบที่เกี่ยวข้อง แสดงใต้ช่องกรอก


# ที่มาของราคากลาง ตามนิยาม "ราคากลาง" พ.ร.บ. มาตรา 4 (1)-(6)
REFERENCE_PRICE_SOURCES = [
    {"value": "1", "label": "(1) ราคาที่ได้มาจากการคำนวณตามหลักเกณฑ์ที่คณะกรรมการราคากลางกำหนด"},
    {"value": "2", "label": "(2) ราคาที่ได้มาจากฐานข้อมูลราคาอ้างอิงของพัสดุที่กรมบัญชีกลางจัดทำ"},
    {"value": "3", "label": "(3) ราคามาตรฐานที่สำนักงบประมาณหรือหน่วยงานกลางอื่นกำหนด"},
    {"value": "4", "label": "(4) ราคาที่ได้มาจากการสืบราคาจากท้องตลาด"},
    {"value": "5", "label": "(5) ราคาที่เคยซื้อหรือจ้างครั้งหลังสุดภายในระยะเวลาสองปีงบประมาณ"},
    {"value": "6", "label": "(6) ราคาอื่นใดตามหลักเกณฑ์ วิธีการ หรือแนวทางปฏิบัติของหน่วยงานของรัฐนั้น ๆ"},
]

_DOC_HEADER = [
    FieldSpec(name="doc_no", label_th="ที่ (เลขที่หนังสือ)", type="text", max_length=50),
    FieldSpec(name="doc_date", label_th="วันที่", type="date"),
]

STEP_FORMS: dict[str, list[FieldSpec]] = {
    "PURCHASE_REQUEST_REPORT": [
        *_DOC_HEADER,
        FieldSpec(name="reason_th", label_th="เหตุผลและความจำเป็นที่ต้องซื้อหรือจ้าง", type="textarea",
                  max_length=3000, help_th="ระเบียบ ข้อ 22(1)"),
        FieldSpec(name="spec_summary", label_th="รายละเอียดของพัสดุ/ขอบเขตของงาน", type="textarea",
                  max_length=5000, help_th="ระเบียบ ข้อ 22(2)"),
        FieldSpec(name="reference_price", label_th="ราคากลาง (บาท)", type="money", min=0.01,
                  help_th="ระเบียบ ข้อ 22(3)"),
        FieldSpec(name="reference_price_source", label_th="ที่มาของราคากลาง", type="select",
                  options=REFERENCE_PRICE_SOURCES, help_th="พ.ร.บ. มาตรา 4"),
        FieldSpec(name="delivery_days", label_th="กำหนดเวลาที่ต้องการใช้พัสดุ (วัน)", type="integer",
                  min=1, max=3650, help_th="ระเบียบ ข้อ 22(5)"),
        FieldSpec(name="evaluation_criteria", label_th="หลักเกณฑ์การพิจารณาคัดเลือกข้อเสนอ", type="select",
                  options=[{"value": "PRICE", "label": "เกณฑ์ราคา"},
                           {"value": "PRICE_PERFORMANCE", "label": "เกณฑ์ราคาประกอบเกณฑ์อื่น"}],
                  help_th="พ.ร.บ. มาตรา 65, ระเบียบ ข้อ 22(7)"),
        FieldSpec(name="inspection_committee", label_th="ผู้ตรวจรับ/คณะกรรมการตรวจรับพัสดุ",
                  type="personnel_multi", min_items=1,
                  help_th="วงเงินไม่เกิน 100,000 บาท แต่งตั้งผู้ตรวจรับ 1 คนได้ (ระเบียบ ข้อ 25)"),
    ],
    "INVITATION": [
        *_DOC_HEADER,
        FieldSpec(name="invited_vendors", label_th="ผู้ประกอบการที่ได้รับหนังสือเชิญชวน", type="vendor_multi",
                  min_items=pr.MIN_INVITED_VENDORS_SELECTION, help_th="พ.ร.บ. มาตรา 56(1) — ไม่น้อยกว่า 3 ราย"),
        FieldSpec(name="submission_deadline", label_th="กำหนดวันยื่นข้อเสนอ", type="date"),
    ],
    "PRICE_AGREEMENT": [
        *_DOC_HEADER,
        FieldSpec(name="vendor_tax_id", label_th="เลขประจำตัวผู้เสียภาษีของผู้เสนอราคา", type="tax_id"),
        FieldSpec(name="vendor_name", label_th="ชื่อผู้เสนอราคา", type="text", max_length=255),
        FieldSpec(name="quoted_amount", label_th="ราคาที่เสนอ (บาท)", type="money", min=0.01),
        FieldSpec(name="agreed_amount", label_th="ราคาที่ตกลงซื้อหรือจ้าง (บาท)", type="money", min=0.01,
                  lte_field="quoted_amount", help_th="ระเบียบ ข้อ 79 — เจรจาตกลงราคา"),
    ],
    "AWARD_APPROVAL": [
        *_DOC_HEADER,
        FieldSpec(name="winner_tax_id", label_th="เลขประจำตัวผู้เสียภาษีของผู้ได้รับคัดเลือก", type="tax_id"),
        FieldSpec(name="award_amount", label_th="ราคาที่อนุมัติสั่งซื้อ/สั่งจ้าง (บาท)", type="money", min=0.01),
        FieldSpec(name="extra_budget_approved", label_th="ได้รับอนุมัติเงินเพิ่ม (กรณีราคาเกินวงเงิน)",
                  type="checkbox", required=False, help_th="ระเบียบ ข้อ 57"),
        FieldSpec(name="extra_budget_ref", label_th="เลขที่หนังสืออนุมัติเงินเพิ่ม", type="text", max_length=100,
                  show_if=ShowIf(field="extra_budget_approved", equals=True)),
    ],
    "PURCHASE_ORDER": [
        FieldSpec(name="po_no", label_th="เลขที่ใบสั่งซื้อ/สั่งจ้าง", type="text", max_length=50),
        FieldSpec(name="po_date", label_th="วันที่สั่งซื้อ/สั่งจ้าง", type="date"),
        FieldSpec(name="delivery_due_date", label_th="กำหนดส่งมอบภายในวันที่", type="date"),
        FieldSpec(name="penalty_rate_percent", label_th="อัตราค่าปรับรายวัน (ร้อยละ)", type="percent",
                  min=0.01, max=0.20, help_th="ระเบียบ ข้อ 162: ร้อยละ 0.01–0.20 ของราคาพัสดุที่ยังไม่ได้รับมอบ"),
        FieldSpec(name="warranty_days", label_th="ระยะเวลารับประกันความชำรุดบกพร่อง (วัน)", type="integer",
                  min=0, max=3650, required=False),
    ],
}


def form_for(step_code: str) -> list[FieldSpec]:
    """ขั้นตอนที่ไม่มีฟอร์มเฉพาะ ใช้หัวหนังสือมาตรฐาน + หมายเหตุ."""
    return STEP_FORMS.get(step_code, [
        *_DOC_HEADER,
        FieldSpec(name="remarks", label_th="หมายเหตุ", type="textarea", required=False, max_length=2000),
    ])


# ---------------------------------------------------------------------------
# Server-side validation (ตรรกะเดียวกับ frontend/src/validation.ts + กฎข้ามช่อง)
# ---------------------------------------------------------------------------
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _visible(spec: FieldSpec, data: dict[str, Any]) -> bool:
    return spec.show_if is None or data.get(spec.show_if.field) == spec.show_if.equals


def _to_decimal(raw: Any) -> Decimal | None:
    # ไม่รับ float จาก JSON เป็นเงิน — ต้องเป็น string/int เพื่อกัน precision error
    if isinstance(raw, bool) or isinstance(raw, float):
        return None
    try:
        d = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() and d.as_tuple().exponent >= -2 else None


def validate_step_data(step_code: str, data: dict[str, Any], ctx: dict[str, Any]) -> tuple[dict[str, Any], list[pr.RuleViolation]]:
    """คืน (ข้อมูลที่ normalize แล้ว, รายการข้อผิดพลาด). ctx = ข้อมูลโครงการ เช่น budget_amount, method."""
    specs = form_for(step_code)
    known = {s.name for s in specs}
    errors: list[pr.RuleViolation] = []
    clean: dict[str, Any] = {}

    unknown = set(data) - known
    if unknown:  # mass-assignment protection: ปฏิเสธฟิลด์ที่ไม่ได้ประกาศไว้
        errors.append(pr.RuleViolation("UNKNOWN_FIELDS", f"ฟิลด์ไม่รู้จัก: {sorted(unknown)}"))

    for spec in specs:
        raw = data.get(spec.name)
        if not _visible(spec, data):
            continue
        empty = raw is None or raw == "" or raw == [] or (spec.type == "checkbox" and raw is False)
        if empty:
            if spec.required or spec.show_if is not None:
                if spec.type != "checkbox":
                    errors.append(pr.RuleViolation("REQUIRED", f"กรุณากรอก{spec.label_th}", spec.name))
            if spec.type == "checkbox":
                clean[spec.name] = False
            continue

        def bad(msg: str, spec: FieldSpec = spec) -> None:
            errors.append(pr.RuleViolation("INVALID", msg, spec.name, spec.help_th))

        match spec.type:
            case "text" | "textarea" | "select":
                if not isinstance(raw, str):
                    bad(f"{spec.label_th} ต้องเป็นข้อความ"); continue
                value = clean_text(raw)
                if spec.max_length and len(value) > spec.max_length:
                    bad(f"{spec.label_th} ยาวเกิน {spec.max_length} ตัวอักษร"); continue
                if spec.options and value not in {o["value"] for o in spec.options}:
                    bad(f"{spec.label_th} ไม่อยู่ในตัวเลือกที่กำหนด"); continue
                clean[spec.name] = value
            case "money" | "percent":
                value = _to_decimal(raw)
                if value is None:
                    bad(f"{spec.label_th} ต้องเป็นตัวเลขทศนิยมไม่เกิน 2 ตำแหน่ง (ส่งเป็นข้อความ)"); continue
                if spec.min is not None and value < Decimal(str(spec.min)):
                    bad(f"{spec.label_th} ต้องไม่น้อยกว่า {spec.min}"); continue
                if spec.max is not None and value > Decimal(str(spec.max)):
                    bad(f"{spec.label_th} ต้องไม่เกิน {spec.max}"); continue
                clean[spec.name] = value
            case "integer":
                if not isinstance(raw, int) or isinstance(raw, bool):
                    bad(f"{spec.label_th} ต้องเป็นจำนวนเต็ม"); continue
                if (spec.min is not None and raw < spec.min) or (spec.max is not None and raw > spec.max):
                    bad(f"{spec.label_th} ต้องอยู่ระหว่าง {spec.min:g} ถึง {spec.max:g}"); continue
                clean[spec.name] = raw
            case "date":
                try:
                    if not isinstance(raw, str) or not _ISO_DATE.match(raw):
                        raise ValueError
                    clean[spec.name] = date.fromisoformat(raw)
                except ValueError:
                    bad(f"{spec.label_th} ต้องอยู่ในรูปแบบ YYYY-MM-DD")
            case "checkbox":
                if not isinstance(raw, bool):
                    bad(f"{spec.label_th} ต้องเป็น true/false"); continue
                clean[spec.name] = raw
            case "tax_id":
                if not isinstance(raw, str) or not is_valid_thai_tax_id(raw):
                    bad("เลขประจำตัวผู้เสียภาษี 13 หลักไม่ถูกต้อง (checksum ไม่ผ่าน)"); continue
                clean[spec.name] = raw
            case "personnel_multi" | "vendor_multi":
                if not isinstance(raw, list) or not all(isinstance(x, int) and not isinstance(x, bool) for x in raw):
                    bad(f"{spec.label_th} ต้องเป็นรายการรหัส"); continue
                if len(set(raw)) != len(raw):
                    bad(f"{spec.label_th} มีรายการซ้ำ"); continue
                if spec.min_items and len(raw) < spec.min_items:
                    bad(f"{spec.label_th} ต้องมีอย่างน้อย {spec.min_items} รายการ"); continue
                clean[spec.name] = raw

    # กฎข้ามช่อง (cross-field) ทั่วไป
    for spec in specs:
        if spec.lte_field and spec.name in clean and spec.lte_field in clean \
                and clean[spec.name] > clean[spec.lte_field]:
            errors.append(pr.RuleViolation("LTE_FIELD", f"{spec.label_th} ต้องไม่เกินค่าของช่อง {spec.lte_field}",
                                           spec.name, spec.help_th))

    errors.extend(_step_business_rules(step_code, clean, ctx))
    return clean, errors


def _step_business_rules(step_code: str, clean: dict[str, Any], ctx: dict[str, Any]) -> list[pr.RuleViolation]:
    """กฎทางระเบียบเฉพาะขั้นตอน — เรียก rule engine กลาง."""
    budget: Decimal = ctx["budget_amount"]
    out: list[pr.RuleViolation] = []
    if step_code == "PURCHASE_REQUEST_REPORT" and "inspection_committee" in clean:
        n = len(clean["inspection_committee"])
        if n == 1 and budget > pr.SMALL_PURCHASE_MAX:
            out.append(pr.RuleViolation("SOLE_INSPECTOR_NOT_ALLOWED",
                                        "วงเงินเกิน 100,000 บาท ต้องแต่งตั้งคณะกรรมการตรวจรับอย่างน้อย 3 คน",
                                        "inspection_committee", "ระเบียบ ข้อ 25"))
        elif 1 < n < 3:
            out.append(pr.RuleViolation("MIN_MEMBERS", "คณะกรรมการตรวจรับต้องมีอย่างน้อย 3 คน",
                                        "inspection_committee", "ระเบียบ ข้อ 25"))
    if step_code == "AWARD_APPROVAL" and "award_amount" in clean:
        out += pr.validate_award(budget, clean["award_amount"], clean.get("extra_budget_approved", False))
    if step_code == "PRICE_AGREEMENT" and "agreed_amount" in clean:
        out += pr.validate_award(budget, clean["agreed_amount"], field="agreed_amount")
    if step_code == "PURCHASE_ORDER" and {"po_date", "delivery_due_date"} <= clean.keys() \
            and clean["delivery_due_date"] < clean["po_date"]:
        out.append(pr.RuleViolation("DATE_ORDER", "กำหนดส่งมอบต้องไม่ก่อนวันที่สั่งซื้อ", "delivery_due_date"))
    return out
