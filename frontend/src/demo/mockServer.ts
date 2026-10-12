/**
 * เซิร์ฟเวอร์จำลองในเบราว์เซอร์ — ใช้เฉพาะเวอร์ชันสาธิตบนเว็บ (build ด้วย `npm run build:demo`)
 *
 * ข้อมูลตั้งต้น (snapshot.json) บันทึกจากคำตอบของ API จริงบนฐานข้อมูลตัวอย่าง จึงมีรูปแบบตรงกับระบบจริงทุกช่อง
 * การบันทึกข้อมูล (สร้างโครงการ, กรอกขั้นตอน, อนุมัติ, ทะเบียนผู้ประกอบการ) ทำงานจริงในหน่วยความจำของเบราว์เซอร์
 * ด้วยกฎชุดเดียวกับ backend (เพดานวงเงิน, ลำดับขั้นตอน, SoD, บัญชีผู้ทิ้งงาน, checksum เลขผู้เสียภาษี)
 * — โหลดหน้าใหม่แล้วข้อมูลกลับเป็นค่าตั้งต้น ไม่มีข้อมูลใดถูกส่งออกจากเครื่องผู้ใช้
 *
 * ฟังก์ชันที่ต้องใช้เซิร์ฟเวอร์จริง (สร้างไฟล์ Word/PDF/Excel, ส่ง LINE, สำรอง/กู้คืน, จัดการผู้ใช้/แบบฟอร์ม)
 * ตอบกลับเป็นข้อความอธิบายแทน
 */
import { validateProjectDraft } from "../projectValidation";
import type {
  AuditRow, FieldSpec, MethodInfo, ProjectDetail, ProjectDraft, ProjectListItem, StepFormResponse,
  VendorDetail, VendorListItem, Violation,
} from "../types";
import { isValidThaiTaxId, validateForm } from "../validation";
import { DEMO_PASSWORD } from "./accounts";
import raw from "./snapshot.json";

interface Me { user_id: number; username: string; full_name_th: string; roles: string[]; permissions: string[] }
interface Snapshot {
  me: Record<string, Me>;
  methods: MethodInfo[];
  departments: { department_id: number; code: string; name_th: string }[];
  personnel: unknown[];
  projects: ProjectListItem[];
  project_detail: Record<string, ProjectDetail & { reference_price: string | null }>;
  step_forms: Record<string, StepFormResponse>;
  workflow: Record<string, { small: WorkflowStep[]; large: WorkflowStep[] }>;
  vendors: VendorListItem[];
  vendor_detail: Record<string, VendorDetail>;
  dashboard: Record<string, unknown>;
  admin: Record<string, unknown> & { audit: { items: AuditRow[]; next_before_id: number | null } };
}
interface WorkflowStep { order: number; code: string; name_th: string; legal_ref: string | null; document: string | null; min_announce_working_days?: number }

// สำเนาที่แก้ไขได้ (ไม่แตะ object ที่ import มา)
const db: Snapshot = structuredClone(raw as unknown as Snapshot);

/** เก็บ FieldSpec ต่อรหัสขั้นตอน (backend ใช้ form_for(step_code) ชุดเดียวกันทุกโครงการ) */
const fieldsByStep = new Map<string, FieldSpec[]>();
for (const [key, f] of Object.entries(db.step_forms)) fieldsByStep.set(key.split("/")[1]!, f.fields);

/** ผู้เสนอแต่ละขั้น (ตรวจ SoD) — ข้อมูลตั้งต้นถือว่าเสนอโดย officer */
const submittedBy = new Map<string, string>();
for (const [key, f] of Object.entries(db.step_forms)) if (f.step.status === "SUBMITTED") submittedBy.set(key, "officer");

let nextProjectId = Math.max(...db.projects.map((p) => p.project_id)) + 1;
let nextVendorId = Math.max(...db.vendors.map((v) => v.vendor_id)) + 1;
let nextAuditId = Math.max(0, ...db.admin.audit.items.map((a) => a.audit_id)) + 1;

const SPECIFIC_MAX = 500_000;
const PUBLIC_HEARING_OVER = 5_000_000;
const DEMO_SERVER_ONLY = "ฟังก์ชันนี้ต้องใช้เซิร์ฟเวอร์จริง จึงปิดไว้ในเวอร์ชันสาธิต";

// ---------------------------------------------------------------------------
class HttpError extends Error {
  constructor(public status: number, message: string, public violations: Partial<Violation>[] = []) { super(message); }
}
const rule = (code: string, message: string, field: string | null = null, legal_ref: string | null = null,
              severity: "ERROR" | "WARNING" = "ERROR"): Violation => ({ code, message, field, legal_ref, severity });
const failRules = (violations: Violation[]) => new HttpError(422, "ข้อมูลไม่ผ่านการตรวจสอบตามระเบียบ", violations);

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function userOf(headers: Headers): Me {
  const m = /^Bearer demo\.(\w+)$/.exec(headers.get("authorization") ?? "");
  const me = m ? db.me[m[1]!] : undefined;
  if (!me) throw new HttpError(401, "กรุณาเข้าสู่ระบบ");
  return me;
}
function need(me: Me, ...perms: string[]) {
  if (!perms.some((p) => me.permissions.includes(p))) throw new HttpError(403, "ไม่มีสิทธิ์ดำเนินการนี้");
}

function audit(me: Me, action: string, entity_table: string, entity_id: string | number, new_values: Record<string, unknown>) {
  const hex = Array.from(crypto.getRandomValues(new Uint8Array(32)), (b) => b.toString(16).padStart(2, "0")).join("");
  db.admin.audit.items.unshift({
    audit_id: nextAuditId++, occurred_at: new Date().toISOString(), username: me.username, action,
    entity_table, entity_id: String(entity_id), ip_address: "127.0.0.1", old_values: null, new_values, row_hash: hex,
  });
}

const money = (n: number) => n.toFixed(2);
const num = (v: unknown) => Number(v ?? 0);

// ---------------------------------------------------------------------------
// โครงการ
// ---------------------------------------------------------------------------
function workflowFor(method: string, budget: number): WorkflowStep[] {
  const w = db.workflow[method];
  if (!w) throw new HttpError(404, "ไม่พบวิธีจัดซื้อจัดจ้าง");
  const base = budget > PUBLIC_HEARING_OVER ? w.large : w.small;
  const days = budget <= 5e6 ? 5 : budget <= 1e7 ? 10 : budget <= 5e7 ? 12 : 20;   // ระเบียบ ข้อ 45/46
  return base.map((s) => (method === "E_BIDDING" ? { ...s, min_announce_working_days: days } : s));
}

function projectRules(body: Record<string, unknown>): Violation[] {
  const method = db.methods.find((m) => m.code === body.method_code);
  if (!method) return [rule("METHOD_UNKNOWN", "ไม่พบวิธีจัดซื้อจัดจ้าง", "method_code")];
  const draft: ProjectDraft = {
    project_code: String(body.project_code ?? ""), egp_project_no: String(body.egp_project_no ?? ""),
    fiscal_year_be: String(body.fiscal_year_be ?? ""), title_th: String(body.title_th ?? ""),
    reason_th: String(body.reason_th ?? ""), department_id: String(body.department_id ?? ""),
    method_code: method.code, justification_id: body.justification_id ? String(body.justification_id) : "",
    procurement_type: String(body.procurement_type ?? ""), budget_amount: String(body.budget_amount ?? ""),
    reference_price: body.reference_price ? String(body.reference_price) : "",
    delivery_days: String(body.delivery_days ?? ""),
    items: ((body.items as Record<string, unknown>[]) ?? []).map((i) => ({
      description: String(i.description ?? ""), quantity: String(i.quantity ?? ""),
      unit_th: String(i.unit_th ?? ""), unit_price: String(i.unit_price ?? ""),
    })),
  };
  const v: Violation[] = [];
  // ชั้นที่ 2 ตรวจซ้ำด้วยกฎเดียวกับหน้าจอ (ไม่เชื่อข้อมูลจาก client)
  for (const [field, message] of Object.entries(validateProjectDraft(draft, method))) {
    if (message) v.push(rule("INVALID_FIELD", String(message), field.startsWith("item") ? "items" : field));
  }
  const budget = num(body.budget_amount);
  const just = method.justifications.find((j) => j.id === Number(body.justification_id));
  if (method.code === "SPECIFIC" && just?.clause_ref === "มาตรา 56(2)(ข)" && budget > SPECIFIC_MAX
      && !v.some((x) => x.field === "budget_amount")) {
    v.push(rule("BUDGET_EXCEEDS_SPECIFIC_LIMIT",
      `วงเงิน ${budget.toLocaleString("th-TH", { minimumFractionDigits: 2 })} บาท เกินเพดาน 500,000 บาท ของวิธีเฉพาะเจาะจงตามมาตรา 56(2)(ข)`,
      "budget_amount", "พ.ร.บ. มาตรา 56(2)(ข) ประกอบกฎกระทรวง พ.ศ. 2560"));
  }
  if (body.reference_price && num(body.reference_price) > budget) {
    v.push(rule("REFERENCE_PRICE_OVER_BUDGET", "ราคากลางสูงกว่าวงเงินงบประมาณ — ต้องเตรียมต่อรองราคาหรือขออนุมัติเงินเพิ่ม",
      "reference_price", "ระเบียบ ข้อ 57", "WARNING"));
  }
  if (method.code === "SPECIFIC") {
    // แบ่งซื้อแบ่งจ้าง: หน่วยงานเดียวกัน คำสำคัญเดียวกัน ยอดรวมเกินเพดานเฉพาะเจาะจง
    const keyword = draft.items[0]?.description.split(/\s+/)[0] ?? "";
    const dept = db.departments.find((d) => d.department_id === Number(body.department_id))?.name_th;
    const related = db.projects.filter((p) => p.method.code === "SPECIFIC" && p.department_name_th === dept
      && p.status !== "CANCELLED" && keyword && p.title_th.includes(keyword) && p.fiscal_year_be === Number(body.fiscal_year_be));
    const total = budget + related.reduce((s, p) => s + num(p.budget_amount), 0);
    if (related.length && budget <= SPECIFIC_MAX && total > SPECIFIC_MAX) {
      v.push(rule("POSSIBLE_SPLIT_PURCHASE",
        `พบการจัดซื้อลักษณะเดียวกัน ${related.length} รายการ ยอดรวม ${total.toLocaleString("th-TH", { minimumFractionDigits: 2 })} บาท เกิน 500,000 บาท — อาจเข้าข่ายแบ่งซื้อแบ่งจ้าง`,
        "budget_amount", "พ.ร.บ. (หลักห้ามแบ่งซื้อแบ่งจ้าง)", "WARNING"));
    }
  }
  return v;
}

function createProject(me: Me, body: Record<string, unknown>) {
  need(me, "project:write");
  const v = projectRules(body);
  const errors = v.filter((x) => x.severity === "ERROR");
  const warnings = v.filter((x) => x.severity === "WARNING");
  if (errors.length || (warnings.length && !body.acknowledge_warnings)) throw failRules(v);
  if (db.projects.some((p) => p.project_code === body.project_code && p.fiscal_year_be === Number(body.fiscal_year_be))) {
    throw failRules([rule("DUPLICATE_PROJECT_CODE", "เลขที่โครงการนี้มีอยู่แล้วในปีงบประมาณเดียวกัน", "project_code")]);
  }
  const method = db.methods.find((m) => m.code === body.method_code)!;
  const budget = num(body.budget_amount);
  const id = nextProjectId++;
  const flow = [{ code: "CREATE_PROJECT", name_th: "สร้างโครงการ", legal_ref: "ระเบียบ ข้อ 11 (แผนจัดซื้อจัดจ้าง)", document: null },
    ...workflowFor(method.code, budget).filter((s) => s.code !== "CREATE_PROJECT")];
  const detail = {
    project_id: id, project_code: String(body.project_code), title_th: String(body.title_th),
    method: { code: method.code, name_th: method.name_th }, status: "IN_PROGRESS", budget_amount: money(budget),
    reference_price: body.reference_price ? money(num(body.reference_price)) : null, row_version: 1,
    steps: flow.map((s, i) => ({ code: s.code, name_th: s.name_th, legal_ref: s.legal_ref,
                                status: (i === 0 ? "APPROVED" : "PENDING") as ProjectDetail["steps"][number]["status"],
                                has_document: s.document !== null })),
  };
  db.project_detail[id] = detail;
  for (const s of detail.steps) {
    db.step_forms[`${id}/${s.code}`] = {
      step: { code: s.code, name_th: s.name_th, legal_ref: s.legal_ref, status: s.status },
      fields: fieldsByStep.get(s.code) ?? [], values: {},
      context: { budget_amount: money(budget), method: method.code, small_purchase_max: "100000" }, row_version: 1,
    };
  }
  db.projects.unshift({
    project_id: id, project_code: detail.project_code, title_th: detail.title_th, fiscal_year_be: Number(body.fiscal_year_be),
    department_name_th: db.departments.find((d) => d.department_id === Number(body.department_id))?.name_th ?? "",
    method: { code: method.code, name_th: method.name_th }, budget_amount: detail.budget_amount, status: "IN_PROGRESS",
    progress: { done: 0, total: 0 }, current_step: null,
  });
  audit(me, "CREATE", "projects", id, { project_code: detail.project_code, title_th: detail.title_th, budget_amount: detail.budget_amount });
  return { project_id: id, warnings };
}

/** progress/current_step ของรายการคำนวณจากขั้นตอนจริงทุกครั้ง (เหมือน view ใน backend) */
function listItem(p: ProjectListItem): ProjectListItem {
  const d = db.project_detail[p.project_id];
  if (!d) return p;
  const done = d.steps.filter((s) => s.status === "APPROVED" || s.status === "SKIPPED").length;
  const cur = d.steps.find((s) => s.status !== "APPROVED" && s.status !== "SKIPPED");
  return { ...p, status: d.status, progress: { done, total: d.steps.length },
           current_step: cur ? { code: cur.code, name_th: cur.name_th, status: cur.status } : null };
}

function listProjects(q: URLSearchParams) {
  const text = (q.get("q") ?? "").trim().toLowerCase();
  return db.projects.map(listItem).filter((p) =>
    (!text || p.title_th.toLowerCase().includes(text) || p.project_code.toLowerCase().includes(text))
    && (!q.get("fiscal_year") || p.fiscal_year_be === Number(q.get("fiscal_year")))
    && (!q.get("method") || p.method.code === q.get("method"))
    && (!q.get("status") || p.status === q.get("status")))
    .slice(0, Number(q.get("limit") ?? 50));
}

function projectOf(id: number) {
  const d = db.project_detail[id];
  if (!d) throw new HttpError(404, "ไม่พบโครงการ");
  return d;
}
function formOf(id: number, code: string): StepFormResponse {
  const d = projectOf(id);
  const f = db.step_forms[`${id}/${code}`];
  if (!f) throw new HttpError(404, "ไม่พบขั้นตอนในโครงการนี้");
  const status = d.steps.find((s) => s.code === code)!.status;
  return { ...f, step: { ...f.step, status }, row_version: d.row_version };
}

function eligibleVendor(taxId: unknown, field: string) {
  const v = db.vendors.find((x) => x.tax_id === taxId);
  if (!v) throw failRules([rule("VENDOR_NOT_FOUND", "ไม่พบผู้ประกอบการในทะเบียน กรุณาลงทะเบียนก่อน", field)]);
  if (v.is_sanctioned) throw failRules([rule("VENDOR_SANCTIONED", "ผู้ประกอบการอยู่ในบัญชีรายชื่อผู้ทิ้งงาน", field, "พ.ร.บ. มาตรา 109")]);
  return v;
}

function submitStep(me: Me, id: number, code: string, body: { data: Record<string, unknown>; row_version: number }) {
  need(me, "step:submit");
  const d = projectOf(id);
  if (d.row_version !== body.row_version) throw new HttpError(409, "ข้อมูลโครงการถูกแก้ไขโดยผู้อื่น กรุณาโหลดใหม่");
  const idx = d.steps.findIndex((s) => s.code === code);
  if (idx < 0) throw failRules([rule("STEP_NOT_IN_WORKFLOW", `ขั้นตอน ${code} ไม่อยู่ใน workflow ของวิธีนี้`)]);
  const pending = d.steps.slice(0, idx).find((s) => s.status !== "APPROVED" && s.status !== "SKIPPED");
  if (pending) throw failRules([rule("PREVIOUS_STEP_PENDING", `ต้องดำเนินการขั้นตอน ${pending.code} ให้เสร็จก่อน`)]);
  const step = d.steps[idx]!;
  if (!["PENDING", "IN_PROGRESS", "REJECTED"].includes(step.status)) {
    throw failRules([rule("STEP_LOCKED", "ขั้นตอนนี้ส่งพิจารณาหรืออนุมัติแล้ว แก้ไขไม่ได้")]);
  }
  const form = formOf(id, code);
  const errs = validateForm(form.fields, body.data as never, form.context);
  if (Object.keys(errs).length) throw failRules(Object.entries(errs).map(([f, m]) => rule("INVALID_FIELD", m, f)));
  for (const f of ["vendor_tax_id", "winner_tax_id"]) if (body.data[f]) eligibleVendor(body.data[f], f);
  if (code === "AWARD_APPROVAL") {
    const agreed = db.step_forms[`${id}/PRICE_AGREEMENT`]?.values;
    if (agreed?.vendor_tax_id && agreed.vendor_tax_id !== body.data.winner_tax_id) {
      throw failRules([rule("WINNER_NOT_BIDDER", "ผู้ได้รับคัดเลือกต้องเป็นผู้ที่ยื่นข้อเสนอในโครงการนี้", "winner_tax_id")]);
    }
    if (num(body.data.award_amount) > num(d.budget_amount)) {
      throw failRules([rule("AWARD_EXCEEDS_BUDGET", "ราคาที่เสนอสูงกว่าวงเงิน ต้องต่อรองราคาหรือได้รับอนุมัติเงินเพิ่มก่อน", "award_amount", "ระเบียบ ข้อ 57")]);
    }
  }
  if (code === "PURCHASE_REQUEST_REPORT" && body.data.reference_price) d.reference_price = money(num(body.data.reference_price));
  step.status = "SUBMITTED";
  db.step_forms[`${id}/${code}`]!.values = body.data as never;
  submittedBy.set(`${id}/${code}`, me.username);
  d.row_version += 1;
  audit(me, "STEP_SUBMIT", "project_steps", `${id}:${code}`, body.data);
  return { status: step.status, row_version: d.row_version };
}

function decideStep(me: Me, id: number, code: string, body: { approve: boolean; comment?: string | null }) {
  need(me, "step:approve");
  const d = projectOf(id);
  const step = d.steps.find((s) => s.code === code);
  if (!step || step.status !== "SUBMITTED") throw failRules([rule("STEP_NOT_SUBMITTED", "ขั้นตอนนี้ยังไม่ได้ส่งพิจารณา")]);
  if (submittedBy.get(`${id}/${code}`) === me.username) {
    // Segregation of Duties: ผู้จัดทำ/เสนอ ต้องไม่ใช่ผู้อนุมัติ
    throw failRules([rule("SOD_VIOLATION", "ผู้เสนอไม่สามารถอนุมัติรายการของตนเองได้")]);
  }
  step.status = body.approve ? "APPROVED" : "REJECTED";
  if (body.approve) {
    if (code === "AWARD_APPROVAL") d.status = "AWARDED";
    if (code === d.steps[d.steps.length - 1]!.code) d.status = code === "CONTRACT" ? "CONTRACTED" : "COMPLETED";
    if (code === "AWARD_APPROVAL") recordAward(d);
  }
  d.row_version += 1;
  audit(me, body.approve ? "STEP_APPROVE" : "STEP_REJECT", "project_steps", `${id}:${code}`, { comment: body.comment ?? null });
  return { status: step.status, project_status: d.status };
}

/** อนุมัติสั่งซื้อแล้ว → ประวัติการเสนอราคา/ชนะของผู้ประกอบการ */
function recordAward(d: ProjectDetail) {
  const award = db.step_forms[`${d.project_id}/AWARD_APPROVAL`]?.values ?? {};
  const price = db.step_forms[`${d.project_id}/PRICE_AGREEMENT`]?.values ?? {};
  const v = db.vendors.find((x) => x.tax_id === award.winner_tax_id);
  if (!v) return;
  v.bids += 1;
  v.wins += 1;
  v.awarded_total = money(num(v.awarded_total) + num(award.award_amount));
  const p = db.projects.find((x) => x.project_id === d.project_id)!;
  db.vendor_detail[v.vendor_id]?.projects.unshift({
    project_id: d.project_id, project_code: d.project_code, title_th: d.title_th, fiscal_year_be: p.fiscal_year_be,
    method_name_th: d.method.name_th, quoted_amount: String(price.quoted_amount ?? award.award_amount),
    agreed_amount: String(award.award_amount), is_winner: true,
  });
}

// ---------------------------------------------------------------------------
// ผู้ประกอบการ
// ---------------------------------------------------------------------------
const maskPhone = (p: string) => `xxx-xxx-${p.slice(-4)}`;
const maskBank = (b: string) => `${"x".repeat(Math.max(0, b.length - 4))}${b.slice(-4)}`;

function listVendors(q: URLSearchParams) {
  const text = (q.get("q") ?? "").replace(/-/g, "").trim().toLowerCase();
  return db.vendors.filter((v) =>
    (!text || v.name_th.toLowerCase().includes(text) || v.tax_id.includes(text))
    && (!q.get("vendor_type") || v.vendor_type === q.get("vendor_type"))
    && (!q.get("sanctioned") || String(v.is_sanctioned) === q.get("sanctioned")))
    .slice(0, Number(q.get("limit") ?? 100));
}

function vendorFieldErrors(b: Record<string, unknown>, creating: boolean): Violation[] {
  const v: Violation[] = [];
  if (creating) {
    if (!isValidThaiTaxId(String(b.tax_id ?? ""))) v.push(rule("INVALID_TAX_ID", "เลขประจำตัวผู้เสียภาษีไม่ถูกต้อง (checksum ไม่ผ่าน)", "tax_id"));
    else if (b.vendor_type === "JURISTIC" && !String(b.tax_id).startsWith("0")) v.push(rule("INVALID_TAX_ID", "เลขทะเบียนนิติบุคคลต้องขึ้นต้นด้วย 0", "tax_id"));
    else if (b.vendor_type === "INDIVIDUAL" && String(b.tax_id).startsWith("0")) v.push(rule("INVALID_TAX_ID", "เลขประจำตัวประชาชนต้องไม่ขึ้นต้นด้วย 0", "tax_id"));
  } else if ("tax_id" in b) v.push(rule("extra_forbidden", "แก้ไขเลขประจำตัวผู้เสียภาษีไม่ได้", "tax_id"));
  for (const f of ["name_th", "address_th"]) {
    if ((creating || f in b) && !String(b[f] ?? "").trim()) v.push(rule("REQUIRED", "ต้องระบุ", f));
  }
  if (b.email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(String(b.email))) v.push(rule("INVALID_EMAIL", "อีเมลไม่ถูกต้อง", "email"));
  if (b.phone && !/^0\d{8,9}$/.test(String(b.phone))) v.push(rule("INVALID_PHONE", "เบอร์โทรศัพท์ไม่ถูกต้อง", "phone"));
  if (b.bank_account && !/^\d{10,15}$/.test(String(b.bank_account))) v.push(rule("INVALID_BANK", "เลขบัญชีธนาคารไม่ถูกต้อง", "bank_account"));
  return v;
}
const invalid = (v: Violation[]) => new HttpError(422, "รูปแบบข้อมูลไม่ถูกต้อง", v);

function createVendor(me: Me, b: Record<string, unknown>) {
  need(me, "vendor:write");
  const v = vendorFieldErrors(b, true);
  if (v.length) throw invalid(v);
  if (db.vendors.some((x) => x.tax_id === b.tax_id)) throw new HttpError(409, "ผู้ประกอบการนี้มีในทะเบียนแล้ว");
  const id = nextVendorId++;
  const base = { vendor_id: id, tax_id: String(b.tax_id), vendor_type: b.vendor_type as VendorListItem["vendor_type"],
                 name_th: String(b.name_th).trim(), is_sanctioned: false };
  db.vendors.unshift({ ...base, bids: 0, wins: 0, awarded_total: 0 });
  db.vendor_detail[id] = {
    ...base, address_th: String(b.address_th).trim(), email: (b.email as string) || null,
    phone_masked: b.phone ? maskPhone(String(b.phone)) : null, bank_account_masked: b.bank_account ? maskBank(String(b.bank_account)) : null,
    created_at: new Date().toISOString(), sanctions: [], projects: [],
  };
  audit(me, "CREATE", "vendors", id, { tax_id: base.tax_id, name_th: base.name_th, phone: "[REDACTED]", bank_account: "[REDACTED]" });
  return { vendor_id: id };
}

function patchVendor(me: Me, id: number, b: Record<string, unknown>) {
  need(me, "vendor:write");
  const d = db.vendor_detail[id];
  if (!d) throw new HttpError(404, "ไม่พบผู้ประกอบการ");
  const v = vendorFieldErrors(b, false);
  if (v.length) throw invalid(v);
  if ("name_th" in b) d.name_th = String(b.name_th).trim();
  if ("address_th" in b) d.address_th = String(b.address_th).trim();
  if ("email" in b) d.email = (b.email as string) || null;
  if ("phone" in b) d.phone_masked = b.phone ? maskPhone(String(b.phone)) : null;
  if ("bank_account" in b) d.bank_account_masked = b.bank_account ? maskBank(String(b.bank_account)) : null;
  const row = db.vendors.find((x) => x.vendor_id === id);
  if (row) row.name_th = d.name_th;
  audit(me, "UPDATE", "vendors", id, Object.fromEntries(Object.keys(b).map((k) => [k, ["phone", "bank_account"].includes(k) ? "[REDACTED]" : b[k]])));
  return { vendor_id: id };
}

function addSanction(me: Me, id: number, b: Record<string, unknown>) {
  need(me, "vendor:sanction");
  const d = db.vendor_detail[id];
  if (!d) throw new HttpError(404, "ไม่พบผู้ประกอบการ");
  const from = String(b.effective_from ?? "");
  const to = b.effective_to ? String(b.effective_to) : null;
  const v: Violation[] = [];
  if (!["ABANDONED_WORK", "SUSPENDED"].includes(String(b.sanction_type))) v.push(rule("INVALID", "ประเภทไม่ถูกต้อง", "sanction_type"));
  if (!String(b.reference_no ?? "").trim()) v.push(rule("REQUIRED", "ต้องระบุเลขที่หนังสือแจ้งเวียน", "reference_no"));
  if (!/^\d{4}-\d{2}-\d{2}$/.test(from)) v.push(rule("REQUIRED", "ต้องระบุวันที่มีผล", "effective_from"));
  if (to && to < from) v.push(rule("DATE_ORDER", "วันที่สิ้นสุดต้องไม่ก่อนวันที่มีผล", "effective_to"));
  if (v.length) throw invalid(v);
  const today = new Date().toISOString().slice(0, 10);
  const active = from <= today && (!to || to >= today);
  const sanction_id = Date.now();
  d.sanctions.unshift({ sanction_id, sanction_type: b.sanction_type as never, reference_no: String(b.reference_no),
                        effective_from: from, effective_to: to, is_active: active });
  d.is_sanctioned = d.is_sanctioned || active;
  const row = db.vendors.find((x) => x.vendor_id === id);
  if (row) row.is_sanctioned = d.is_sanctioned;
  audit(me, "SANCTION", "vendor_sanctions", sanction_id, { vendor_id: id, ...b });
  return { sanction_id };
}

// ---------------------------------------------------------------------------
function auditList(q: URLSearchParams) {
  const items = db.admin.audit.items.filter((a) =>
    (!q.get("action") || a.action === q.get("action"))
    && (!q.get("username") || (a.username ?? "").includes(q.get("username")!))
    && (!q.get("date_from") || a.occurred_at.slice(0, 10) >= q.get("date_from")!)
    && (!q.get("date_to") || a.occurred_at.slice(0, 10) <= q.get("date_to")!)
    && (!q.get("before_id") || a.audit_id < Number(q.get("before_id"))));
  const limit = Number(q.get("limit") ?? 50);
  const page = items.slice(0, limit);
  return { items: page, next_before_id: items.length > limit ? page[page.length - 1]!.audit_id : null };
}

function emptyDashboard(fy: number) {
  return { fiscal_year: fy, kpi: { project_count: 0, budget_total: 0, award_total: 0, savings_total: 0 },
           monthly_by_method: [], by_method_status: [] };
}

type Route = [method: string, pattern: RegExp, handler: (ctx: Ctx) => unknown];
interface Ctx { m: RegExpExecArray; q: URLSearchParams; body: Record<string, unknown>; headers: Headers; me: () => Me }

const routes: Route[] = [
  ["POST", /^\/api\/auth\/login$/, ({ body }) => {
    const u = db.me[String(body.username ?? "")];
    if (!u || body.password !== DEMO_PASSWORD) throw new HttpError(401, "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง");
    audit(u, "LOGIN", "users", u.user_id, {});
    return { access_token: `demo.${u.username}`, token_type: "bearer" };
  }],
  ["GET", /^\/api\/auth\/me$/, ({ me }) => me()],
  ["POST", /^\/api\/auth\/change-password$/, () => { throw new HttpError(400, `${DEMO_SERVER_ONLY} (บัญชีสาธิตใช้รหัสผ่านร่วมกัน)`); }],

  ["GET", /^\/api\/methods$/, ({ me }) => (me(), db.methods)],
  ["GET", /^\/api\/departments$/, ({ me }) => (me(), db.departments)],
  ["GET", /^\/api\/personnel$/, ({ me }) => (me(), db.personnel)],
  ["GET", /^\/api\/workflow\/(\w+)$/, ({ m, q, me }) => (me(), workflowFor(m[1]!, num(q.get("budget"))))],
  ["POST", /^\/api\/projects\/validate$/, ({ me, body }) => (need(me(), "project:write"), { violations: projectRules(body) })],
  ["POST", /^\/api\/projects$/, ({ me, body }) => createProject(me(), body)],
  ["GET", /^\/api\/projects$/, ({ me, q }) => (me(), listProjects(q))],
  ["GET", /^\/api\/projects\/(\d+)$/, ({ me, m }) => (me(), projectOf(Number(m[1]))) ],
  ["GET", /^\/api\/projects\/(\d+)\/steps\/(\w+)\/form$/, ({ me, m }) => (me(), formOf(Number(m[1]), m[2]!))],
  ["POST", /^\/api\/projects\/(\d+)\/steps\/(\w+)\/submit$/, ({ me, m, body }) => submitStep(me(), Number(m[1]), m[2]!, body as never)],
  ["POST", /^\/api\/projects\/(\d+)\/steps\/(\w+)\/decision$/, ({ me, m, body }) => decideStep(me(), Number(m[1]), m[2]!, body as never)],
  ["POST", /^\/api\/projects\/\d+\/steps\/\w+\/(export|share-line)/, ({ me }) => {
    need(me(), "document:export");
    throw new HttpError(400, "การสร้างเอกสาร Word/PDF ตามแบบฟอร์มกรมบัญชีกลางและการส่ง LINE ต้องใช้เซิร์ฟเวอร์จริง — ปิดไว้ในเวอร์ชันสาธิต");
  }],

  ["GET", /^\/api\/vendors$/, ({ me, q }) => (me(), listVendors(q))],
  ["POST", /^\/api\/vendors$/, ({ me, body }) => createVendor(me(), body)],
  ["GET", /^\/api\/vendors\/(\d+)$/, ({ me, m }) => {
    me();
    const d = db.vendor_detail[Number(m[1])];
    if (!d) throw new HttpError(404, "ไม่พบผู้ประกอบการ");
    return d;
  }],
  ["PATCH", /^\/api\/vendors\/(\d+)$/, ({ me, m, body }) => patchVendor(me(), Number(m[1]), body)],
  ["POST", /^\/api\/vendors\/(\d+)\/sanctions$/, ({ me, m, body }) => addSanction(me(), Number(m[1]), body)],

  ["GET", /^\/api\/dashboard\/summary$/, ({ me, q }) => {
    need(me(), "dashboard:view");
    const fy = q.get("fiscal_year") ?? "";
    return db.dashboard[fy] ?? emptyDashboard(Number(fy));
  }],
  ["GET", /^\/api\/dashboard\/report\.xlsx$/, () => { throw new HttpError(400, `${DEMO_SERVER_ONLY} (สร้างไฟล์ Excel)`); }],

  ["GET", /^\/api\/admin\/audit$/, ({ me, q }) => (need(me(), "audit:read"), auditList(q))],
  ["GET", /^\/api\/admin\/audit\/verify$/, ({ me }) => (need(me(), "audit:read"), db.admin.audit_verify)],
  ["GET", /^\/api\/admin\/(users|roles|templates|line-channels|backups|personnel-without-account|document-types)$/, ({ me, m }) => {
    need(me(), "user:manage", "backup:run", "template:manage", "template:verify", "audit:read", "line:manage");
    return db.admin[m[1]!.replace(/-/g, "_")];
  }],
  ["*", /^\/api\/admin\//, ({ me }) => { me(); throw new HttpError(400, DEMO_SERVER_ONLY); }],
];

async function handle(path: string, init: RequestInit): Promise<Response> {
  const url = new URL(path, location.origin);
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  let body: Record<string, unknown> = {};
  if (typeof init.body === "string") {
    try { body = JSON.parse(init.body); } catch { return json(422, { message: "รูปแบบข้อมูลไม่ถูกต้อง", violations: [] }); }
  }
  await new Promise((r) => setTimeout(r, 120));   // ให้เห็นสถานะ "กำลังบันทึก…" เหมือนเรียกเซิร์ฟเวอร์จริง
  for (const [rm, re, fn] of routes) {
    const m = re.exec(url.pathname);
    if (!m || (rm !== "*" && rm !== method)) continue;
    try {
      const out = fn({ m, q: url.searchParams, body, headers, me: () => userOf(headers) });
      return json(method === "POST" && /\/(projects|vendors|sanctions)$/.test(url.pathname) ? 201 : 200, structuredClone(out));
    } catch (e) {
      if (e instanceof HttpError) return json(e.status, { message: e.message, violations: e.violations });
      console.error(e);
      return json(500, { message: "เกิดข้อผิดพลาดในเซิร์ฟเวอร์จำลอง", violations: [] });
    }
  }
  return json(404, { message: "ไม่พบ endpoint", violations: [] });
}

/** แทน window.fetch สำหรับ /api/* เท่านั้น (ทรัพยากรอื่น เช่น ฟอนต์ ยังโหลดตามปกติ) */
export function installMockServer(): void {
  const realFetch = window.fetch.bind(window);
  window.fetch = (input: RequestInfo | URL, init: RequestInit = {}) => {
    const path = typeof input === "string" ? input : input instanceof URL ? input.pathname + input.search : input.url;
    return path.startsWith("/api/") ? handle(path, init) : realFetch(input, init);
  };
}
