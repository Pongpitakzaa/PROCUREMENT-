from datetime import date
from decimal import Decimal as D

import pytest

from app.rules import procurement_rules as pr
from app.rules.step_forms import validate_step_data
from app.rules.validators import baht_text, fiscal_year_be, is_valid_thai_tax_id, thai_date

VALID_TAX_ID = "0105536092641"   # checksum ถูกต้อง (เลขตัวอย่าง)


@pytest.mark.parametrize("value,ok", [
    (VALID_TAX_ID, True),
    ("0105536092642", False),        # checksum ผิด
    ("1234567890121", True),
    ("123456789012", False),         # 12 หลัก
    ("01055360926a1", False),
    ("", False),
])
def test_tax_id_checksum(value, ok):
    assert is_valid_thai_tax_id(value) is ok


@pytest.mark.parametrize("amount,text", [
    (D("0"), "ศูนย์บาทถ้วน"),
    (D("1"), "หนึ่งบาทถ้วน"),
    (D("11"), "สิบเอ็ดบาทถ้วน"),
    (D("21"), "ยี่สิบเอ็ดบาทถ้วน"),
    (D("101"), "หนึ่งร้อยเอ็ดบาทถ้วน"),
    (D("1250.50"), "หนึ่งพันสองร้อยห้าสิบบาทห้าสิบสตางค์"),
    (D("500000"), "ห้าแสนบาทถ้วน"),
    (D("1000000"), "หนึ่งล้านบาทถ้วน"),
    (D("1000001"), "หนึ่งล้านเอ็ดบาทถ้วน"),
    (D("21000000.25"), "ยี่สิบเอ็ดล้านบาทยี่สิบห้าสตางค์"),
])
def test_baht_text(amount, text):
    assert baht_text(amount) == text


def test_fiscal_year_and_thai_date():
    assert fiscal_year_be(date(2026, 9, 30)) == 2569
    assert fiscal_year_be(date(2026, 10, 1)) == 2570
    assert thai_date(date(2026, 10, 12)) == "12 ตุลาคม 2569"


def test_specific_56_2_b_ceiling():
    over = pr.ProjectFacts(pr.Method.SPECIFIC, D("500000.01"), "มาตรา 56(2)(ข)")
    assert [v.code for v in pr.validate_method_and_budget(over)] == ["BUDGET_EXCEEDS_SPECIFIC_LIMIT"]
    at_limit = pr.ProjectFacts(pr.Method.SPECIFIC, D("500000"), "มาตรา 56(2)(ข)")
    assert pr.validate_method_and_budget(at_limit) == []
    # อนุมาตราอื่น (เช่น ผู้ประกอบการรายเดียว) ไม่มีเพดานนี้
    sole = pr.ProjectFacts(pr.Method.SPECIFIC, D("3000000"), "มาตรา 56(2)(ค)")
    assert pr.validate_method_and_budget(sole) == []


def test_general_invitation_floor_and_warnings():
    low = pr.ProjectFacts(pr.Method.E_BIDDING, D("400000"))
    assert pr.validate_method_and_budget(low)[0].code == "BUDGET_TOO_LOW_FOR_GENERAL_INVITATION"
    ref_over = pr.ProjectFacts(pr.Method.E_BIDDING, D("1000000"), reference_price=D("1100000"))
    (v,) = pr.validate_method_and_budget(ref_over)
    assert v.severity == pr.Severity.WARNING and pr.errors_only([v]) == []


def test_committee_rules():
    three = [pr.CommitteeMemberFacts(1, "CHAIR"), pr.CommitteeMemberFacts(2, "MEMBER"),
             pr.CommitteeMemberFacts(3, "MEMBER")]
    assert pr.validate_committee("BID_EVALUATION", three, D("1000000")) == []
    assert {v.code for v in pr.validate_committee("BID_EVALUATION", three[:2], D("1000000"))} == {"MIN_MEMBERS"}
    sole = [pr.CommitteeMemberFacts(1, "SOLE_INSPECTOR")]
    assert pr.validate_committee("INSPECTION", sole, D("100000")) == []
    assert pr.validate_committee("INSPECTION", sole, D("100000.01"))[0].code == "SOLE_INSPECTOR_NOT_ALLOWED"
    assert pr.validate_committee_separation([1, 2, 3], [3, 4, 5])[0].code == "COMMITTEE_OVERLAP"


def test_selection_needs_three_vendors_and_sanctions():
    quotes = [pr.QuotationFacts(VALID_TAX_ID, D("100")), pr.QuotationFacts("1234567890121", D("90"), True)]
    codes = {v.code for v in pr.validate_quotations(pr.Method.SELECTION, quotes)}
    assert codes == {"MIN_INVITED_VENDORS", "VENDOR_SANCTIONED"}


def test_split_purchase_detection():
    hist = [pr.PastPurchase(1, "GOODS", "คอมพิวเตอร์", D("450000"), date(2026, 10, 1))]
    hit = pr.detect_split_purchase(1, "GOODS", "คอมพิวเตอร์", D("100000"), date(2026, 10, 12), hist)
    assert hit and hit[0].severity == pr.Severity.WARNING
    old = [pr.PastPurchase(1, "GOODS", "คอมพิวเตอร์", D("450000"), date(2026, 8, 1))]
    assert pr.detect_split_purchase(1, "GOODS", "คอมพิวเตอร์", D("100000"), date(2026, 10, 12), old) == []


def test_conditional_public_hearing_step_and_ordering():
    steps = [pr.WorkflowStepDef(1, "A", "a"), pr.WorkflowStepDef(2, "HEARING", "h", D("5000000")),
             pr.WorkflowStepDef(3, "B", "b")]
    assert [s.code for s in pr.applicable_steps(steps, D("5000000"))] == ["A", "B"]
    assert [s.code for s in pr.applicable_steps(steps, D("5000000.01"))] == ["A", "HEARING", "B"]
    assert pr.can_start_step(["A", "B"], set(), "B").code == "PREVIOUS_STEP_PENDING"
    assert pr.can_start_step(["A", "B"], {"A"}, "B") is None


def test_e_bidding_announce_days_and_working_days():
    assert pr.e_bidding_min_announce_days(D("5000000")) == 5
    assert pr.e_bidding_min_announce_days(D("5000000.01")) == 10
    assert pr.e_bidding_min_announce_days(D("80000000")) == 20
    # ศุกร์ 9 ต.ค. 2569 + 7 วันทำการ → พุธ 21 ต.ค. (ข้ามเสาร์-อาทิตย์ และวันหยุด 13 ต.ค.)
    assert pr.add_working_days(date(2026, 10, 9), 7, frozenset({date(2026, 10, 13)})) == date(2026, 10, 21)


def test_step_form_validation_mirrors_frontend():
    ctx = {"budget_amount": D("80000"), "method": "SPECIFIC"}
    clean, errs = validate_step_data("PRICE_AGREEMENT", {
        "doc_no": "พด 0001/2570", "doc_date": "2026-10-12", "vendor_tax_id": VALID_TAX_ID,
        "vendor_name": "บริษัท ตัวอย่าง จำกัด", "quoted_amount": "80000.00", "agreed_amount": "79500.00"}, ctx)
    assert errs == [] and clean["agreed_amount"] == D("79500.00")

    _, errs = validate_step_data("PRICE_AGREEMENT", {
        "doc_no": "x", "doc_date": "12/10/2569", "vendor_tax_id": "0105536092642", "vendor_name": "x",
        "quoted_amount": 80000.5, "agreed_amount": "90000", "status": "APPROVED"}, ctx)
    codes = {(e.code, e.field) for e in errs}
    assert ("UNKNOWN_FIELDS", None) in codes                      # mass assignment
    assert ("INVALID", "doc_date") in codes                       # รูปแบบวันที่
    assert ("INVALID", "vendor_tax_id") in codes                  # checksum
    assert ("INVALID", "quoted_amount") in codes                  # float ห้ามใช้กับเงิน
    assert ("AWARD_EXCEEDS_BUDGET", "agreed_amount") in codes     # ราคาตกลง > วงเงิน


def test_step_form_show_if_and_sole_inspector():
    ctx = {"budget_amount": D("150000"), "method": "SPECIFIC"}
    _, errs = validate_step_data("AWARD_APPROVAL", {
        "doc_no": "1", "doc_date": "2026-10-12", "winner_tax_id": VALID_TAX_ID, "award_amount": "160000",
        "extra_budget_approved": True}, ctx)
    assert [e.field for e in errs] == ["extra_budget_ref"]        # ต้องกรอกเมื่อติ๊กอนุมัติเงินเพิ่ม
    _, errs = validate_step_data("PURCHASE_REQUEST_REPORT", {
        "doc_no": "1", "doc_date": "2026-10-12", "reason_th": "r", "spec_summary": "s",
        "reference_price": "150000", "reference_price_source": "4", "delivery_days": 30,
        "evaluation_criteria": "PRICE", "inspection_committee": [7]}, ctx)
    assert [e.code for e in errs] == ["SOLE_INSPECTOR_NOT_ALLOWED"]
