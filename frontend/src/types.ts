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
