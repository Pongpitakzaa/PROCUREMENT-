"""ORM mapping ของ database/schema.sql (schema หลักอยู่ที่ SQL — ORM นี้ map ตามนั้น ไม่ใช้ create_all).

ใช้ ORM/Core ทุกจุด → ทุก query เป็น parameterized query อัตโนมัติ (กัน SQL Injection)
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import BigInteger, ForeignKey, Numeric, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import BYTEA, INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

Money = Numeric(15, 2)


class Department(Base):
    __tablename__ = "departments"
    department_id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name_th: Mapped[str] = mapped_column(String(255))
    parent_department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.department_id"))


class Personnel(Base):
    __tablename__ = "personnel"
    personnel_id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.department_id"))
    title_th: Mapped[str] = mapped_column(String(50))
    first_name_th: Mapped[str] = mapped_column(String(100))
    last_name_th: Mapped[str] = mapped_column(String(100))
    position_th: Mapped[str] = mapped_column(String(150))
    employment_type: Mapped[str] = mapped_column(String(30))
    citizen_id_enc: Mapped[bytes] = mapped_column(BYTEA)
    citizen_id_hmac: Mapped[str] = mapped_column(String(64), unique=True)
    is_active: Mapped[bool] = mapped_column(default=True)

    @property
    def full_name_th(self) -> str:
        return f"{self.title_th}{self.first_name_th} {self.last_name_th}"


class Role(Base):
    __tablename__ = "roles"
    role_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name_th: Mapped[str] = mapped_column(String(100))


class UserRole(Base):
    __tablename__ = "user_roles"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.role_id"), primary_key=True)


class User(Base):
    __tablename__ = "users"
    user_id: Mapped[int] = mapped_column(primary_key=True)
    personnel_id: Mapped[int] = mapped_column(ForeignKey("personnel.personnel_id"), unique=True)
    username: Mapped[str] = mapped_column(String(60), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True)
    failed_login_count: Mapped[int] = mapped_column(SmallInteger, default=0)
    locked_until: Mapped[datetime | None]
    password_changed_at: Mapped[datetime]
    last_login_at: Mapped[datetime | None]

    personnel: Mapped[Personnel] = relationship(lazy="joined")
    roles: Mapped[list[Role]] = relationship(secondary="user_roles", lazy="selectin")

    @property
    def role_codes(self) -> set[str]:
        return {r.code for r in self.roles}


class ProcurementMethod(Base):
    __tablename__ = "procurement_methods"
    method_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    category: Mapped[str] = mapped_column(String(30))
    name_th: Mapped[str] = mapped_column(String(150))
    legal_basis: Mapped[str] = mapped_column(String(255))
    min_budget_exclusive: Mapped[Decimal | None] = mapped_column(Money)
    max_budget_inclusive: Mapped[Decimal | None] = mapped_column(Money)


class MethodJustification(Base):
    __tablename__ = "method_justifications"
    justification_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    method_id: Mapped[int] = mapped_column(ForeignKey("procurement_methods.method_id"))
    clause_ref: Mapped[str] = mapped_column(String(40))
    description_th: Mapped[str] = mapped_column(Text)
    max_budget_inclusive: Mapped[Decimal | None] = mapped_column(Money)


class DocumentType(Base):
    __tablename__ = "document_types"
    document_type_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name_th: Mapped[str] = mapped_column(String(255))


class CommitteeType(Base):
    __tablename__ = "committee_types"
    committee_type_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name_th: Mapped[str] = mapped_column(String(255))
    min_members: Mapped[int] = mapped_column(SmallInteger)


class WorkflowStep(Base):
    __tablename__ = "workflow_steps"
    step_id: Mapped[int] = mapped_column(primary_key=True)
    method_id: Mapped[int] = mapped_column(ForeignKey("procurement_methods.method_id"))
    step_order: Mapped[int] = mapped_column(SmallInteger)
    code: Mapped[str] = mapped_column(String(50))
    name_th: Mapped[str] = mapped_column(String(255))
    legal_ref: Mapped[str | None] = mapped_column(String(255))
    output_document_type_id: Mapped[int | None] = mapped_column(ForeignKey("document_types.document_type_id"))
    required_committee_type_id: Mapped[int | None] = mapped_column(ForeignKey("committee_types.committee_type_id"))
    applies_when_budget_over: Mapped[Decimal | None] = mapped_column(Money)

    output_document_type: Mapped[DocumentType | None] = relationship(lazy="joined")


class Vendor(Base):
    __tablename__ = "vendors"
    vendor_id: Mapped[int] = mapped_column(primary_key=True)
    tax_id: Mapped[str] = mapped_column(String(13), unique=True)
    vendor_type: Mapped[str] = mapped_column(String(20))
    name_th: Mapped[str] = mapped_column(String(255))
    address_th: Mapped[str] = mapped_column(Text)
    phone_enc: Mapped[bytes | None] = mapped_column(BYTEA)
    email: Mapped[str | None] = mapped_column(String(255))
    bank_account_enc: Mapped[bytes | None] = mapped_column(BYTEA)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class VendorSanction(Base):
    __tablename__ = "vendor_sanctions"
    sanction_id: Mapped[int] = mapped_column(primary_key=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.vendor_id"))
    sanction_type: Mapped[str] = mapped_column(String(30))
    reference_no: Mapped[str] = mapped_column(String(100))
    effective_from: Mapped[date]
    effective_to: Mapped[date | None]


class Project(Base):
    __tablename__ = "projects"
    project_id: Mapped[int] = mapped_column(primary_key=True)
    project_code: Mapped[str] = mapped_column(String(30), unique=True)
    egp_project_no: Mapped[str | None] = mapped_column(String(11), unique=True)
    fiscal_year_be: Mapped[int] = mapped_column(SmallInteger)
    title_th: Mapped[str] = mapped_column(String(500))
    reason_th: Mapped[str] = mapped_column(Text)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.department_id"))
    method_id: Mapped[int] = mapped_column(ForeignKey("procurement_methods.method_id"))
    justification_id: Mapped[int | None] = mapped_column(ForeignKey("method_justifications.justification_id"))
    procurement_type: Mapped[str] = mapped_column(String(20))
    budget_amount: Mapped[Decimal] = mapped_column(Money)
    reference_price: Mapped[Decimal | None] = mapped_column(Money)
    delivery_days: Mapped[int] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.user_id"))
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    row_version: Mapped[int] = mapped_column(default=1)

    method: Mapped[ProcurementMethod] = relationship(lazy="joined")
    department: Mapped[Department] = relationship(lazy="joined")
    justification: Mapped[MethodJustification | None] = relationship(lazy="joined")
    items: Mapped[list["ProjectItem"]] = relationship(order_by="ProjectItem.line_no", cascade="all, delete-orphan")

    # optimistic locking: UPDATE ... WHERE row_version = :old → ถ้ามีคนแก้ก่อน จะได้ StaleDataError
    __mapper_args__ = {"version_id_col": row_version}


class ProjectItem(Base):
    __tablename__ = "project_items"
    item_id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.project_id", ondelete="CASCADE"))
    line_no: Mapped[int] = mapped_column(SmallInteger)
    description: Mapped[str] = mapped_column(String(500))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    unit_th: Mapped[str] = mapped_column(String(50))
    unit_price: Mapped[Decimal] = mapped_column(Money)

    @property
    def line_total(self) -> Decimal:
        return self.quantity * self.unit_price


class ProjectStep(Base):
    __tablename__ = "project_steps"
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.project_id", ondelete="CASCADE"), primary_key=True)
    step_id: Mapped[int] = mapped_column(ForeignKey("workflow_steps.step_id"), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    submitted_by: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"))
    submitted_at: Mapped[datetime | None]
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"))
    approved_at: Mapped[datetime | None]
    step_data: Mapped[dict] = mapped_column(JSONB, default=dict)

    step: Mapped[WorkflowStep] = relationship(lazy="joined")


class Quotation(Base):
    __tablename__ = "quotations"
    quotation_id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.project_id", ondelete="CASCADE"))
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.vendor_id"))
    quoted_amount: Mapped[Decimal] = mapped_column(Money)
    agreed_amount: Mapped[Decimal | None] = mapped_column(Money)
    submitted_at: Mapped[datetime]
    is_qualified: Mapped[bool | None]
    rank_no: Mapped[int | None] = mapped_column(SmallInteger)
    is_winner: Mapped[bool] = mapped_column(default=False)

    vendor: Mapped[Vendor] = relationship(lazy="joined")


class Committee(Base):
    __tablename__ = "committees"
    committee_id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.project_id", ondelete="CASCADE"))
    committee_type_id: Mapped[int] = mapped_column(ForeignKey("committee_types.committee_type_id"))
    order_no: Mapped[str | None] = mapped_column(String(50))
    order_date: Mapped[date | None]

    committee_type: Mapped[CommitteeType] = relationship(lazy="joined")
    members: Mapped[list["CommitteeMember"]] = relationship(order_by="CommitteeMember.seq_no",
                                                           cascade="all, delete-orphan", lazy="selectin")


class CommitteeMember(Base):
    __tablename__ = "committee_members"
    committee_id: Mapped[int] = mapped_column(ForeignKey("committees.committee_id", ondelete="CASCADE"),
                                              primary_key=True)
    personnel_id: Mapped[int] = mapped_column(ForeignKey("personnel.personnel_id"), primary_key=True)
    member_role: Mapped[str] = mapped_column(String(20))
    seq_no: Mapped[int] = mapped_column(SmallInteger)

    personnel: Mapped[Personnel] = relationship(lazy="joined")


class DocumentTemplate(Base):
    __tablename__ = "document_templates"
    template_id: Mapped[int] = mapped_column(primary_key=True)
    document_type_id: Mapped[int] = mapped_column(ForeignKey("document_types.document_type_id"))
    version_label: Mapped[str] = mapped_column(String(30))
    source_url: Mapped[str] = mapped_column(String(500))
    cgd_reference: Mapped[str] = mapped_column(String(255))
    file_format: Mapped[str] = mapped_column(String(5))
    storage_path: Mapped[str] = mapped_column(String(500))
    content: Mapped[bytes | None] = mapped_column(BYTEA, deferred=True)   # โหลดเมื่อต้องสร้างไฟล์คืนเท่านั้น
    sha256: Mapped[str] = mapped_column(String(64))
    variable_schema: Mapped[dict] = mapped_column(JSONB)
    effective_from: Mapped[date]
    is_active: Mapped[bool] = mapped_column(default=False)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.user_id"))
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"))

    document_type: Mapped[DocumentType] = relationship(lazy="joined")


class GeneratedDocument(Base):
    __tablename__ = "generated_documents"
    document_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.project_id"))
    template_id: Mapped[int] = mapped_column(ForeignKey("document_templates.template_id"))
    document_no: Mapped[str | None] = mapped_column(String(50))
    output_format: Mapped[str] = mapped_column(String(5))
    storage_path: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64))
    render_context: Mapped[dict] = mapped_column(JSONB)
    generated_by: Mapped[int] = mapped_column(ForeignKey("users.user_id"))
    generated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class NotificationChannel(Base):
    __tablename__ = "notification_channels"
    channel_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    name_th: Mapped[str] = mapped_column(String(100))
    line_to_enc: Mapped[bytes] = mapped_column(BYTEA)
    line_to_hmac: Mapped[str | None] = mapped_column(String(64), unique=True)
    source: Mapped[str] = mapped_column(String(10), default="MANUAL")
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.department_id"))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class NotificationLog(Base):
    __tablename__ = "notification_logs"
    notification_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("notification_channels.channel_id"))
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.project_id"))
    retry_key: Mapped[UUID]
    status: Mapped[str] = mapped_column(String(10))
    http_status: Mapped[int | None] = mapped_column(SmallInteger)
    sent_by: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"))
    sent_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class BackupJob(Base):
    __tablename__ = "backup_jobs"
    backup_job_id: Mapped[int] = mapped_column(primary_key=True)
    job_type: Mapped[str] = mapped_column(String(10))
    file_name: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(10))
    error_message: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.user_id"))
    started_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    finished_at: Mapped[datetime | None]


class AuditLog(Base):
    __tablename__ = "audit_logs"
    audit_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(server_default=func.clock_timestamp())
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"))
    action: Mapped[str] = mapped_column(String(50))
    entity_table: Mapped[str | None] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(60))
    old_values: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    new_values: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(300))
    request_id: Mapped[UUID | None]
    prev_hash: Mapped[str] = mapped_column(String(64), default="")   # trigger เติมค่าจริง
    row_hash: Mapped[str] = mapped_column(String(64), default="")
