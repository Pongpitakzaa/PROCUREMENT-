"""Rule engine ตามระเบียบพัสดุ (pure business logic — ไม่ผูกกับ DB/HTTP).

ทุกกฎคืนค่าเป็นรายการ RuleViolation แทนการ raise ทันที เพื่อให้หน้าจอแสดงข้อผิดพลาด
ได้ครบทุกข้อในครั้งเดียว และแยกระดับ ERROR (ห้ามบันทึก) กับ WARNING (บันทึกได้แต่ต้องยืนยัน)

อ้างอิง: พ.ร.บ.การจัดซื้อจัดจ้างและการบริหารพัสดุภาครัฐ พ.ศ. 2560 ("พ.ร.บ.")
        ระเบียบกระทรวงการคลังว่าด้วยการจัดซื้อจัดจ้างฯ พ.ศ. 2560 ("ระเบียบ")
        กฎกระทรวงกำหนดวงเงินการจัดซื้อจัดจ้างพัสดุโดยวิธีเฉพาะเจาะจง ฯ พ.ศ. 2560
ค่าเพดานด้านล่างต้องทบทวนให้ตรงกับกฎกระทรวง/หนังสือเวียนฉบับล่าสุดก่อนใช้งานจริง
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Iterable, Sequence

from app.rules.validators import is_valid_thai_tax_id


class Method(StrEnum):
    E_MARKET = "E_MARKET"
    E_BIDDING = "E_BIDDING"
    SELECTION = "SELECTION"
    SPECIFIC = "SPECIFIC"


class Severity(StrEnum):
    ERROR = "ERROR"
    WARNING = "WARNING"


@dataclass(frozen=True)
class RuleViolation:
    code: str
    message: str
    field: str | None = None
    legal_ref: str | None = None
    severity: Severity = Severity.ERROR


# --- เกณฑ์วงเงิน (บาท) ------------------------------------------------------
GENERAL_INVITATION_MIN_EXCLUSIVE = Decimal("500000")   # e-market / e-bidding ใช้เมื่อวงเงินเกิน 5 แสน
SPECIFIC_56_2_B_MAX = Decimal("500000")                # มาตรา 56(2)(ข) + กฎกระทรวง
SMALL_PURCHASE_MAX = Decimal("100000")                 # ระเบียบ ข้อ 79 วรรคสอง / ผู้ตรวจรับคนเดียว
PUBLIC_HEARING_OVER = Decimal("5000000")               # ระเบียบ ข้อ 45: รับฟังความคิดเห็นร่าง TOR
MIN_INVITED_VENDORS_SELECTION = 3                      # พ.ร.บ. มาตรา 56(1): เชิญไม่น้อยกว่า 3 ราย
APPEAL_PERIOD_WORKING_DAYS = 7                         # พ.ร.บ. มาตรา 117
SPLIT_PURCHASE_WINDOW_DAYS = 30

# ระยะเวลาเผยแพร่ประกาศ e-bidding ขั้นต่ำ (วันทำการ) ตามช่วงวงเงิน — ระเบียบ ข้อ 46
E_BIDDING_ANNOUNCE_DAYS: Sequence[tuple[Decimal | None, int]] = (
    (Decimal("5000000"), 5),
    (Decimal("10000000"), 10),
    (Decimal("50000000"), 12),
    (None, 20),
)


# --- Input DTOs (แยกจาก ORM เพื่อให้ rule engine เป็น pure function) -----------
@dataclass(frozen=True)
class ProjectFacts:
    method: Method
    budget_amount: Decimal
    justification_clause: str | None = None       # เช่น "มาตรา 56(2)(ข)"
    reference_price: Decimal | None = None
    items_total: Decimal | None = None


@dataclass(frozen=True)
class CommitteeMemberFacts:
    personnel_id: int
    role: str          # CHAIR | MEMBER | MEMBER_SECRETARY | SOLE_INSPECTOR
    is_active: bool = True
    has_conflict_of_interest: bool = False   # แบบแสดงความบริสุทธิ์ใจ (พ.ร.บ. มาตรา 13)


@dataclass(frozen=True)
class QuotationFacts:
    vendor_tax_id: str
    amount: Decimal
    vendor_sanctioned: bool = False


@dataclass
class WorkflowStepDef:
    step_order: int
    code: str
    name_th: str
    applies_when_budget_over: Decimal | None = None
    extra: dict = field(default_factory=dict)


# --- 1) ความสอดคล้องระหว่างวิธีจัดหากับวงเงิน --------------------------------
def validate_method_and_budget(p: ProjectFacts) -> list[RuleViolation]:
    v: list[RuleViolation] = []
    if p.budget_amount <= 0:
        return [RuleViolation("BUDGET_POSITIVE", "วงเงินงบประมาณต้องมากกว่า 0", "budget_amount")]

    if p.method in (Method.E_MARKET, Method.E_BIDDING) and p.budget_amount <= GENERAL_INVITATION_MIN_EXCLUSIVE:
        v.append(RuleViolation(
            "BUDGET_TOO_LOW_FOR_GENERAL_INVITATION",
            "วงเงินไม่เกิน 500,000 บาท ให้พิจารณาใช้วิธีเฉพาะเจาะจงตามมาตรา 56(2)(ข)",
            "method", "พ.ร.บ. มาตรา 55(1), 56(2)(ข)"))

    if p.method in (Method.SELECTION, Method.SPECIFIC) and not p.justification_clause:
        v.append(RuleViolation(
            "JUSTIFICATION_REQUIRED",
            "วิธีคัดเลือก/เฉพาะเจาะจง ต้องระบุเหตุผลตามอนุมาตราของมาตรา 56",
            "justification_id", "พ.ร.บ. มาตรา 56"))

    if p.method == Method.SPECIFIC and p.justification_clause == "มาตรา 56(2)(ข)" \
            and p.budget_amount > SPECIFIC_56_2_B_MAX:
        v.append(RuleViolation(
            "BUDGET_EXCEEDS_SPECIFIC_LIMIT",
            f"วงเงิน {p.budget_amount:,.2f} บาท เกินเพดาน 500,000 บาท ของวิธีเฉพาะเจาะจงตามมาตรา 56(2)(ข)",
            "budget_amount", "พ.ร.บ. มาตรา 56(2)(ข) ประกอบกฎกระทรวง พ.ศ. 2560"))

    if p.items_total is not None and p.items_total > p.budget_amount:
        v.append(RuleViolation(
            "ITEMS_EXCEED_BUDGET",
            f"ยอดรวมรายการพัสดุ {p.items_total:,.2f} บาท สูงกว่าวงเงินงบประมาณ",
            "items", "ระเบียบ ข้อ 22(4)"))

    if p.reference_price is not None and p.reference_price > p.budget_amount:
        # ราคากลางสูงกว่าวงเงินได้ แต่ต้องมีแผนรองรับ (ต่อรองราคา/ขอเงินเพิ่ม) → เตือน ไม่บล็อก
        v.append(RuleViolation(
            "REFERENCE_PRICE_OVER_BUDGET",
            "ราคากลางสูงกว่าวงเงินงบประมาณ — ต้องเตรียมต่อรองราคาหรือขออนุมัติเงินเพิ่ม",
            "reference_price", "ระเบียบ ข้อ 57", Severity.WARNING))
    return v


# --- 2) คณะกรรมการ -------------------------------------------------------------
def validate_committee(committee_code: str, members: Sequence[CommitteeMemberFacts],
                       budget_amount: Decimal) -> list[RuleViolation]:
    v: list[RuleViolation] = []
    ids = [m.personnel_id for m in members]
    if len(ids) != len(set(ids)):
        v.append(RuleViolation("DUPLICATE_MEMBER", "มีรายชื่อกรรมการซ้ำ", "members"))

    if any(not m.is_active for m in members):
        v.append(RuleViolation("INACTIVE_MEMBER", "มีกรรมการที่พ้นสภาพ/ไม่ปฏิบัติงานแล้ว", "members"))

    if any(m.has_conflict_of_interest for m in members):
        v.append(RuleViolation(
            "CONFLICT_OF_INTEREST", "กรรมการมีส่วนได้เสียกับผู้ยื่นข้อเสนอ ต้องเปลี่ยนตัว",
            "members", "พ.ร.บ. มาตรา 13"))

    # ผู้ตรวจรับคนเดียว: ทำได้เฉพาะวงเงินเล็กน้อยตามกฎกระทรวง (ไม่เกิน 100,000 บาท)
    if committee_code == "INSPECTION" and len(members) == 1:
        if budget_amount > SMALL_PURCHASE_MAX:
            v.append(RuleViolation(
                "SOLE_INSPECTOR_NOT_ALLOWED",
                "วงเงินเกิน 100,000 บาท ต้องแต่งตั้งเป็นคณะกรรมการตรวจรับ (ประธาน + กรรมการอย่างน้อย 2 คน)",
                "members", "ระเบียบ ข้อ 25"))
        return v

    chairs = [m for m in members if m.role == "CHAIR"]
    if len(chairs) != 1:
        v.append(RuleViolation("CHAIR_REQUIRED", "คณะกรรมการต้องมีประธาน 1 คน", "members", "ระเบียบ ข้อ 25"))
    if len(members) < 3:
        v.append(RuleViolation(
            "MIN_MEMBERS", "คณะกรรมการต้องประกอบด้วยประธาน 1 คน และกรรมการอย่างน้อย 2 คน",
            "members", "ระเบียบ ข้อ 25"))
    return v


def validate_committee_separation(evaluation_ids: Iterable[int], inspection_ids: Iterable[int]) -> list[RuleViolation]:
    """ผู้พิจารณาผล/คัดเลือก ห้ามเป็นผู้ตรวจรับในโครงการเดียวกัน (หลักถ่วงดุล ระเบียบ ข้อ 26)."""
    overlap = set(evaluation_ids) & set(inspection_ids)
    if overlap:
        return [RuleViolation(
            "COMMITTEE_OVERLAP",
            f"บุคลากรรหัส {sorted(overlap)} เป็นทั้งกรรมการพิจารณาผลและกรรมการตรวจรับ",
            "members", "ระเบียบ ข้อ 26")]
    return []


# --- 3) ผู้เสนอราคา / ผลการพิจารณา ---------------------------------------------
def validate_quotations(method: Method, quotes: Sequence[QuotationFacts]) -> list[RuleViolation]:
    v: list[RuleViolation] = []
    for i, q in enumerate(quotes):
        if not is_valid_thai_tax_id(q.vendor_tax_id):
            v.append(RuleViolation("INVALID_TAX_ID", f"เลขประจำตัวผู้เสียภาษี {q.vendor_tax_id} ไม่ถูกต้อง",
                                   f"quotations[{i}].vendor_tax_id"))
        if q.vendor_sanctioned:
            v.append(RuleViolation("VENDOR_SANCTIONED", f"ผู้ประกอบการ {q.vendor_tax_id} อยู่ในบัญชีผู้ทิ้งงาน",
                                   f"quotations[{i}]", "พ.ร.บ. มาตรา 109"))

    tax_ids = [q.vendor_tax_id for q in quotes]
    if len(tax_ids) != len(set(tax_ids)):
        v.append(RuleViolation("DUPLICATE_VENDOR", "ผู้ประกอบการรายเดียวกันยื่นซ้ำ", "quotations"))

    if method == Method.SELECTION and len(set(tax_ids)) < MIN_INVITED_VENDORS_SELECTION:
        v.append(RuleViolation(
            "MIN_INVITED_VENDORS",
            "วิธีคัดเลือกต้องเชิญชวนผู้ประกอบการไม่น้อยกว่า 3 ราย (เว้นแต่มีน้อยกว่า 3 ราย — ให้บันทึกเหตุผล)",
            "quotations", "พ.ร.บ. มาตรา 56(1)", Severity.WARNING))
    return v


def validate_award(budget_amount: Decimal, award_amount: Decimal, extra_budget_approved: bool = False,
                   field: str = "award_amount") -> list[RuleViolation]:
    """ราคาที่จะสั่งซื้อต้องไม่เกินวงเงิน เว้นแต่ต่อรองแล้ว/ได้รับอนุมัติเงินเพิ่ม (ระเบียบ ข้อ 57)."""
    if award_amount > budget_amount and not extra_budget_approved:
        return [RuleViolation(
            "AWARD_EXCEEDS_BUDGET",
            f"ราคาที่เสนอ {award_amount:,.2f} บาท สูงกว่าวงเงิน {budget_amount:,.2f} บาท "
            "ต้องต่อรองราคาหรือได้รับอนุมัติเงินเพิ่มก่อน",
            field, "ระเบียบ ข้อ 57")]
    return []


# --- 4) ตรวจจับการแบ่งซื้อแบ่งจ้าง -------------------------------------------
@dataclass(frozen=True)
class PastPurchase:
    department_id: int
    procurement_type: str
    item_keyword: str
    amount: Decimal
    approved_on: date


def detect_split_purchase(department_id: int, procurement_type: str, item_keyword: str,
                          amount: Decimal, today: date, history: Iterable[PastPurchase]) -> list[RuleViolation]:
    """พ.ร.บ. ห้ามแบ่งซื้อแบ่งจ้างเพื่อให้วงเงินต่ำลงจนเปลี่ยนวิธี (เช่น เลี่ยงเกณฑ์ 500,000 บาท).

    heuristic: หน่วยงานเดียวกัน ประเภทเดียวกัน คำสำคัญเดียวกัน ภายใน 30 วัน รวมแล้วเกินเพดานเฉพาะเจาะจง
    → WARNING ให้หัวหน้าเจ้าหน้าที่ยืนยันเหตุผลก่อนดำเนินการต่อ
    """
    window_start = today - timedelta(days=SPLIT_PURCHASE_WINDOW_DAYS)
    related = [h for h in history
               if h.department_id == department_id and h.procurement_type == procurement_type
               and h.item_keyword == item_keyword and h.approved_on >= window_start]
    cumulative = amount + sum((h.amount for h in related), Decimal("0"))
    if related and amount <= SPECIFIC_56_2_B_MAX < cumulative:
        return [RuleViolation(
            "POSSIBLE_SPLIT_PURCHASE",
            f"พบการจัดซื้อลักษณะเดียวกัน {len(related)} รายการใน {SPLIT_PURCHASE_WINDOW_DAYS} วัน "
            f"ยอดรวม {cumulative:,.2f} บาท เกิน 500,000 บาท — อาจเข้าข่ายแบ่งซื้อแบ่งจ้าง",
            "budget_amount", "พ.ร.บ. (หลักห้ามแบ่งซื้อแบ่งจ้าง)", Severity.WARNING)]
    return []


# --- 5) Workflow -----------------------------------------------------------------
def applicable_steps(steps: Sequence[WorkflowStepDef], budget_amount: Decimal) -> list[WorkflowStepDef]:
    """ตัดขั้นตอนแบบมีเงื่อนไขออก เช่น PUBLIC_HEARING มีเฉพาะวงเงิน > 5 ล้านบาท."""
    return sorted(
        (s for s in steps if s.applies_when_budget_over is None or budget_amount > s.applies_when_budget_over),
        key=lambda s: s.step_order,
    )


def can_start_step(ordered_codes: Sequence[str], completed_codes: set[str], target_code: str) -> RuleViolation | None:
    """บังคับลำดับ: ขั้นตอนก่อนหน้าทุกขั้นต้องอนุมัติแล้ว จึงจะเริ่มขั้นถัดไปได้."""
    if target_code not in ordered_codes:
        return RuleViolation("STEP_NOT_IN_WORKFLOW", f"ขั้นตอน {target_code} ไม่อยู่ใน workflow ของวิธีนี้")
    pending = [c for c in ordered_codes[: ordered_codes.index(target_code)] if c not in completed_codes]
    if pending:
        return RuleViolation("PREVIOUS_STEP_PENDING", f"ต้องดำเนินการขั้นตอน {pending[0]} ให้เสร็จก่อน")
    return None


def e_bidding_min_announce_days(budget_amount: Decimal) -> int:
    for upper, days in E_BIDDING_ANNOUNCE_DAYS:
        if upper is None or budget_amount <= upper:
            return days
    raise AssertionError("unreachable")


def add_working_days(start: date, days: int, holidays: frozenset[date] = frozenset()) -> date:
    """นับวันทำการ (ข้ามเสาร์-อาทิตย์และวันหยุดราชการที่ส่งเข้ามา) — ใช้คำนวณวันสิ้นสุดอุทธรณ์/ประกาศ."""
    current, remaining = start, days
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5 and current not in holidays:
            remaining -= 1
    return current


def errors_only(violations: Iterable[RuleViolation]) -> list[RuleViolation]:
    return [x for x in violations if x.severity == Severity.ERROR]
