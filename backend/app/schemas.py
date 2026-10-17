"""Pydantic schemas — ด่านแรกของ backend validation (ชนิดข้อมูล/ความยาว/รูปแบบ).

กฎทางระเบียบที่ต้องใช้ข้อมูลจาก DB (เพดานวงเงินตามวิธี, กรรมการซ้ำ) อยู่ที่ rule engine
และ DB trigger เป็นด่านสุดท้าย → validation 3 ชั้น: Frontend → Pydantic/Rule engine → DB constraint
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (AfterValidator, BaseModel, ConfigDict, EmailStr, Field, StringConstraints,
                      model_validator)

from app.rules.validators import clean_text, is_valid_thai_tax_id

ThaiText = Annotated[str, StringConstraints(min_length=1, max_length=500), AfterValidator(clean_text)]
LongText = Annotated[str, StringConstraints(min_length=1, max_length=5000), AfterValidator(clean_text)]
# เงิน: ต้องเป็นทศนิยมไม่เกิน 2 ตำแหน่ง ไม่เกิน 9,999,999,999,999.99 (ตรงกับ NUMERIC(15,2))
MoneyIn = Annotated[Decimal, Field(gt=0, max_digits=15, decimal_places=2)]


def _check_tax_id(v: str) -> str:
    if not is_valid_thai_tax_id(v):
        raise ValueError("เลขประจำตัวผู้เสียภาษี 13 หลักไม่ถูกต้อง (checksum ไม่ผ่าน)")
    return v


TaxId = Annotated[str, StringConstraints(pattern=r"^\d{13}$"), AfterValidator(_check_tax_id)]


Phone = Annotated[str, StringConstraints(pattern=r"^0\d{8,9}$")]
BankAccount = Annotated[str, StringConstraints(pattern=r"^\d{10,15}$")]


class StrictModel(BaseModel):
    # extra="forbid": ปฏิเสธฟิลด์ที่ไม่ได้ประกาศ (กัน mass assignment เช่นส่ง status=APPROVED มาเอง)
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LoginIn(StrictModel):
    username: Annotated[str, StringConstraints(min_length=3, max_length=60, pattern=r"^[A-Za-z0-9_.-]+$")]
    password: Annotated[str, StringConstraints(min_length=1, max_length=128)]


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class ProjectItemIn(StrictModel):
    description: ThaiText
    quantity: Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]
    unit_th: Annotated[str, StringConstraints(min_length=1, max_length=50)]
    unit_price: Annotated[Decimal, Field(ge=0, max_digits=15, decimal_places=2)]


class ProjectCreate(StrictModel):
    project_code: Annotated[str, StringConstraints(pattern=r"^[A-Z0-9][A-Z0-9/-]{2,29}$")]
    egp_project_no: Annotated[str | None, StringConstraints(pattern=r"^\d{11}$")] = None
    fiscal_year_be: Annotated[int, Field(ge=2560, le=2700)]
    title_th: ThaiText
    reason_th: LongText
    department_id: Annotated[int, Field(gt=0)]
    method_code: Literal["E_MARKET", "E_BIDDING", "SELECTION", "SPECIFIC"]
    justification_id: Annotated[int, Field(gt=0)] | None = None
    procurement_type: Literal["GOODS", "SERVICE", "CONSTRUCTION", "CONSULTANT", "DESIGN"]
    budget_amount: MoneyIn
    reference_price: MoneyIn | None = None
    delivery_days: Annotated[int, Field(ge=1, le=3650)]
    items: Annotated[list[ProjectItemIn], Field(min_length=1, max_length=500)]
    acknowledge_warnings: bool = False   # ผู้ใช้ยืนยันรับทราบคำเตือน (เช่น อาจแบ่งซื้อแบ่งจ้าง)

    @model_validator(mode="after")
    def _justification_needed(self) -> "ProjectCreate":
        if self.method_code in ("SELECTION", "SPECIFIC") and self.justification_id is None:
            raise ValueError("วิธีคัดเลือก/เฉพาะเจาะจง ต้องระบุเหตุผลตาม พ.ร.บ. มาตรา 56")
        return self


class VendorCreate(StrictModel):
    tax_id: TaxId
    vendor_type: Literal["JURISTIC", "INDIVIDUAL"]
    name_th: ThaiText
    address_th: LongText
    phone: Phone | None = None
    email: EmailStr | None = None
    bank_account: BankAccount | None = None

    @model_validator(mode="after")
    def _type_matches_tax_id(self) -> "VendorCreate":
        # เลขทะเบียนนิติบุคคล (กรมพัฒนาธุรกิจการค้า) ขึ้นต้นด้วย 0 เสมอ
        if self.vendor_type == "JURISTIC" and not self.tax_id.startswith("0"):
            raise ValueError("เลขทะเบียนนิติบุคคลต้องขึ้นต้นด้วย 0")
        if self.vendor_type == "INDIVIDUAL" and self.tax_id.startswith("0"):
            raise ValueError("บุคคลธรรมดาให้ใช้เลขประจำตัวประชาชน")
        return self


class VendorUpdate(StrictModel):
    """แก้ไขข้อมูลผู้ประกอบการ (เลขประจำตัวผู้เสียภาษี/ประเภท แก้ไม่ได้ — เป็นตัวตนทางกฎหมาย).

    ช่องที่ไม่ส่งมา = คงค่าเดิม · ส่ง null = ลบค่า (ใช้ model_fields_set แยกสองกรณี)
    """
    name_th: ThaiText | None = None
    address_th: LongText | None = None
    phone: Phone | None = None
    email: EmailStr | None = None
    bank_account: BankAccount | None = None

    @model_validator(mode="after")
    def _required_not_cleared(self) -> "VendorUpdate":
        for f in ("name_th", "address_th"):
            if f in self.model_fields_set and getattr(self, f) is None:
                raise ValueError(f"{f} ห้ามเป็นค่าว่าง")
        return self


class SanctionCreate(StrictModel):
    sanction_type: Literal["ABANDONED_WORK", "SUSPENDED"]
    reference_no: Annotated[str, StringConstraints(min_length=3, max_length=100)]
    effective_from: date
    effective_to: date | None = None

    @model_validator(mode="after")
    def _date_order(self) -> "SanctionCreate":
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("วันสิ้นสุดต้องไม่ก่อนวันเริ่ม")
        return self


Username = Annotated[str, StringConstraints(min_length=3, max_length=60, pattern=r"^[a-z0-9_.-]+$")]
RoleCode = Literal["ADMIN", "PROCUREMENT_OFFICER", "HEAD_OF_PROCUREMENT", "EXECUTIVE", "AUDITOR"]


class ProfileUpdate(StrictModel):
    """ผู้ใช้แก้ไขข้อมูลส่วนตัวของตนเอง — ส่งเฉพาะช่องที่เปลี่ยน · เลขบัตร/หน่วยงาน/บทบาท แก้เองไม่ได้ (ผู้ดูแลเท่านั้น)."""
    title_th: Annotated[str, StringConstraints(min_length=1, max_length=50)] | None = None
    first_name_th: Annotated[str, StringConstraints(min_length=1, max_length=100)] | None = None
    last_name_th: Annotated[str, StringConstraints(min_length=1, max_length=100)] | None = None
    position_th: Annotated[str, StringConstraints(min_length=1, max_length=150)] | None = None
    employment_type: Literal["CIVIL_SERVANT", "GOV_EMPLOYEE", "PERMANENT_EMPLOYEE", "STATE_OFFICIAL", "OTHER"] | None = None


class PersonnelCreate(StrictModel):
    department_id: Annotated[int, Field(gt=0)]
    title_th: Annotated[str, StringConstraints(min_length=1, max_length=50)]
    first_name_th: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    last_name_th: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    position_th: Annotated[str, StringConstraints(min_length=1, max_length=150)]
    employment_type: Literal["CIVIL_SERVANT", "GOV_EMPLOYEE", "PERMANENT_EMPLOYEE", "STATE_OFFICIAL", "OTHER"]
    citizen_id: TaxId   # เลขประจำตัวประชาชนใช้ checksum เดียวกับเลขผู้เสียภาษี

    @model_validator(mode="after")
    def _not_juristic(self) -> "PersonnelCreate":
        if self.citizen_id.startswith("0"):
            raise ValueError("เลขประจำตัวประชาชนไม่ขึ้นต้นด้วย 0 (เลขที่ขึ้นต้นด้วย 0 เป็นเลขนิติบุคคล)")
        return self


class UserCreate(StrictModel):
    """สร้างบัญชี: ผูกกับบุคลากรเดิม (personnel_id) หรือเพิ่มบุคลากรใหม่ (personnel) อย่างใดอย่างหนึ่ง."""
    username: Username
    roles: Annotated[list[RoleCode], Field(min_length=1, max_length=5)]
    personnel_id: Annotated[int, Field(gt=0)] | None = None
    personnel: PersonnelCreate | None = None

    @model_validator(mode="after")
    def _one_personnel_source(self) -> "UserCreate":
        if (self.personnel_id is None) == (self.personnel is None):
            raise ValueError("ระบุบุคลากรเดิม หรือ ข้อมูลบุคลากรใหม่ อย่างใดอย่างหนึ่ง")
        return self


class UserUpdate(StrictModel):
    roles: Annotated[list[RoleCode], Field(min_length=1, max_length=5)] | None = None
    is_active: bool | None = None


class ChangePasswordIn(StrictModel):
    current_password: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    new_password: Annotated[str, StringConstraints(min_length=1, max_length=128)]


class StepSubmitIn(StrictModel):
    # ค่าในฟอร์มตรวจด้วย FieldSpec ของขั้นตอน (app/rules/step_forms.py)
    data: dict[str, object]
    row_version: int   # optimistic locking ของโครงการ


class StepDecisionIn(StrictModel):
    approve: bool
    comment: Annotated[str, StringConstraints(max_length=1000)] | None = None


class LineShareIn(StrictModel):
    channel_id: Annotated[int, Field(gt=0)]
    document_id: Annotated[int, Field(gt=0)] | None = None


class RestoreIn(StrictModel):
    file_name: Annotated[str, StringConstraints(max_length=100)]
    password: Annotated[str, StringConstraints(min_length=1, max_length=128)]   # re-authentication
    confirm_text: Literal["ยืนยันกู้คืนข้อมูล"]                                   # กันกดพลาด


class ViolationOut(BaseModel):
    code: str
    message: str
    field: str | None
    legal_ref: str | None
    severity: str
