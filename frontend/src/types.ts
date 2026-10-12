// ชนิดข้อมูลตรงกับ backend: app/rules/step_forms.py (FieldSpec) และ error shape ของ app/main.py

export type FieldType =
  | "text" | "textarea" | "money" | "percent" | "integer" | "date"
  | "select" | "checkbox" | "tax_id" | "personnel_multi" | "vendor_multi";

export interface FieldSpec {
  name: string;
  label_th: string;
  type: FieldType;
  required: boolean;
  min?: number;
  max?: number;
  max_length?: number;
  min_items?: number;
  options?: { value: string; label: string }[];
  lte_field?: string;
  show_if?: { field: string; equals: unknown };
  help_th?: string;
}

export type FieldValue = string | number | boolean | number[] | undefined;
export type FormValues = Record<string, FieldValue>;

export interface FormContext {
  budget_amount: string;      // เงินส่งเป็น string เสมอ (ห้าม float)
  method: string;
  small_purchase_max: string;
}

export interface StepFormResponse {
  step: { code: string; name_th: string; legal_ref: string | null; status: string };
  fields: FieldSpec[];
  values: FormValues;
  context: FormContext;
  row_version: number;
}

export interface Violation {
  code: string;
  message: string;
  field: string | null;
  legal_ref: string | null;
  severity: "ERROR" | "WARNING";
}

export interface ProjectStepSummary {
  code: string;
  name_th: string;
  legal_ref: string | null;
  status: "PENDING" | "IN_PROGRESS" | "SUBMITTED" | "APPROVED" | "REJECTED" | "SKIPPED";
  has_document: boolean;
}

export interface ProjectDetail {
  project_id: number;
  project_code: string;
  title_th: string;
  method: { code: string; name_th: string };
  status: string;
  budget_amount: string;
  row_version: number;
  steps: ProjectStepSummary[];
}

export type MethodCode = "E_MARKET" | "E_BIDDING" | "SELECTION" | "SPECIFIC";

export interface Justification {
  id: number;
  clause_ref: string;
  description_th: string;
  max_budget_inclusive: string | null;
}

export interface MethodInfo {
  code: MethodCode;
  category: "GENERAL_INVITATION" | "SELECTION" | "SPECIFIC";
  name_th: string;
  legal_basis: string;
  min_budget_exclusive: string | null;
  max_budget_inclusive: string | null;
  justifications: Justification[];
}

export interface Department {
  department_id: number;
  code: string;
  name_th: string;
}

export interface WorkflowPreviewStep {
  order: number;
  code: string;
  name_th: string;
  legal_ref: string | null;
  document: string | null;
  min_announce_working_days?: number;
}

export interface ProjectListItem {
  project_id: number;
  project_code: string;
  title_th: string;
  fiscal_year_be: number;
  department_name_th: string;
  method: { code: MethodCode; name_th: string };
  budget_amount: string;
  status: string;
  progress: { done: number; total: number };
  current_step: { code: string; name_th: string; status: string } | null;
}

/** ค่าที่ผู้ใช้กรอกในฟอร์มสร้างโครงการ — เก็บเป็น string ตามที่พิมพ์ แปลงชนิดตอนส่ง */
export interface ItemDraft {
  description: string;
  quantity: string;
  unit_th: string;
  unit_price: string;
}

export interface ProjectDraft {
  project_code: string;
  egp_project_no: string;
  fiscal_year_be: string;
  title_th: string;
  reason_th: string;
  department_id: string;
  method_code: MethodCode | "";
  justification_id: string;
  procurement_type: string;
  budget_amount: string;
  reference_price: string;
  delivery_days: string;
  items: ItemDraft[];
}

/** ค่าเงินจาก API มาเป็น string (Decimal) หรือ 0 เมื่อไม่มีข้อมูล */
export type ApiMoney = string | number;

export interface DashboardSummary {
  fiscal_year: number;
  kpi: { project_count: number; budget_total: ApiMoney; award_total: ApiMoney; savings_total: ApiMoney };
  monthly_by_method: {
    month: string;            // YYYY-MM (ค.ศ.)
    method_code: MethodCode;
    method_name_th: string;
    project_count: number;
    budget_total: ApiMoney;
    award_total: ApiMoney;
    savings_total: ApiMoney;
  }[];
  by_method_status: {
    method_code: MethodCode;
    method_name_th: string;
    status: string;
    project_count: number;
    budget_total: ApiMoney;
  }[];
}

export type VendorType = "JURISTIC" | "INDIVIDUAL";

export interface VendorListItem {
  vendor_id: number;
  tax_id: string;
  vendor_type: VendorType;
  name_th: string;
  bids: number;
  wins: number;
  awarded_total: ApiMoney;
  is_sanctioned: boolean;
}

export interface VendorSanction {
  sanction_id: number;
  sanction_type: "ABANDONED_WORK" | "SUSPENDED";
  reference_no: string;
  effective_from: string;
  effective_to: string | null;
  is_active: boolean;
}

export interface VendorDetail {
  vendor_id: number;
  tax_id: string;
  vendor_type: VendorType;
  name_th: string;
  address_th: string;
  email: string | null;
  phone_masked: string | null;
  bank_account_masked: string | null;
  created_at: string;
  is_sanctioned: boolean;
  sanctions: VendorSanction[];
  projects: {
    project_id: number;
    project_code: string;
    title_th: string;
    fiscal_year_be: number;
    method_name_th: string;
    quoted_amount: ApiMoney;
    agreed_amount: ApiMoney | null;
    is_winner: boolean;
  }[];
}

export interface VendorDraft {
  tax_id: string;
  vendor_type: VendorType;
  name_th: string;
  address_th: string;
  phone: string;
  email: string;
  bank_account: string;
}
