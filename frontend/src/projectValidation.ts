/**
 * ตรวจฟอร์มสร้างโครงการฝั่ง client — สะท้อน backend/app/schemas.py (ProjectCreate)
 * และ procurement_rules.validate_method_and_budget เพื่อแจ้งผิดทันทีขณะกรอก
 * กฎที่ต้องใช้ข้อมูลในฐานข้อมูล (เช่น ตรวจแบ่งซื้อแบ่งจ้าง) ได้จาก POST /api/projects/validate
 */
import type { ItemDraft, MethodInfo, ProjectDraft } from "./types";
import { toSatang } from "./validation";

export type DraftErrors = Record<string, string>;

const PROJECT_CODE_RE = /^[A-Z0-9][A-Z0-9/-]{2,29}$/;
const EGP_NO_RE = /^\d{11}$/;
const INT_RE = /^\d+$/;

/** ปีงบประมาณ พ.ศ. ปัจจุบัน (เริ่ม 1 ตุลาคม) */
export function currentFiscalYearBE(today = new Date()): number {
  return today.getFullYear() + 543 + (today.getMonth() >= 9 ? 1 : 0);
}

export function emptyItem(): ItemDraft {
  return { description: "", quantity: "", unit_th: "", unit_price: "" };
}

/**
 * ยอดรวมรายการแบบแม่นยำ หน่วย 1/10,000 บาท (จำนวน x100 คูณ ราคา x100) — ตรงกับ Decimal ของ backend
 * null ถ้ามีช่องตัวเลขไม่ถูกต้อง
 */
export function itemsTotalExact(items: ItemDraft[]): bigint | null {
  let total = 0n;
  for (const it of items) {
    const q = toSatang(it.quantity);
    const p = toSatang(it.unit_price);
    if (q === null || p === null) return null;
    total += q * p;
  }
  return total;
}

/** แปลงหน่วย 1/10,000 บาท → สตางค์ (ปัดครึ่งขึ้น) สำหรับแสดงผล */
export const exactToSatang = (v: bigint): bigint => (v + 50n) / 100n;

export function formatBaht(satang: bigint): string {
  const neg = satang < 0n;
  const abs = neg ? -satang : satang;
  const baht = (abs / 100n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${neg ? "-" : ""}${baht}.${(abs % 100n).toString().padStart(2, "0")}`;
}

function money(value: string, { allowZero = false } = {}): string | null {
  const s = toSatang(value);
  if (s === null) return "ต้องเป็นตัวเลข ทศนิยมไม่เกิน 2 ตำแหน่ง";
  if (allowZero ? s < 0n : s <= 0n) return allowZero ? "ต้องไม่ติดลบ" : "ต้องมากกว่า 0";
  return null;
}

export function validateProjectDraft(d: ProjectDraft, method: MethodInfo | undefined): DraftErrors {
  const e: DraftErrors = {};
  const req = (key: keyof ProjectDraft, label: string) => {
    if (!String(d[key]).trim()) e[key] = `กรุณากรอก${label}`;
  };

  if (!PROJECT_CODE_RE.test(d.project_code))
    e.project_code = "ตัวพิมพ์ใหญ่ A-Z ตัวเลข / หรือ - ยาว 3–30 ตัว เช่น PSD-2570-002";
  if (d.egp_project_no && !EGP_NO_RE.test(d.egp_project_no)) e.egp_project_no = "เลขโครงการ e-GP ต้องเป็นตัวเลข 11 หลัก";

  const fy = Number(d.fiscal_year_be);
  if (!INT_RE.test(d.fiscal_year_be) || fy < 2560 || fy > 2700) e.fiscal_year_be = "ปีงบประมาณ พ.ศ. 2560–2700";

  req("title_th", "ชื่อโครงการ");
  if (d.title_th.length > 500) e.title_th = "ยาวเกิน 500 ตัวอักษร";
  req("reason_th", "เหตุผลความจำเป็น");
  if (d.reason_th.length > 5000) e.reason_th = "ยาวเกิน 5,000 ตัวอักษร";
  req("department_id", "หน่วยงาน");
  req("method_code", "วิธีจัดหา");
  req("procurement_type", "ประเภทพัสดุ");

  // พ.ร.บ. มาตรา 56: วิธีคัดเลือก/เฉพาะเจาะจง ต้องอ้างอนุมาตรา
  if (method && method.category !== "GENERAL_INVITATION" && !d.justification_id)
    e.justification_id = "ต้องระบุเหตุผลตาม พ.ร.บ. มาตรา 56";

  const days = Number(d.delivery_days);
  if (!INT_RE.test(d.delivery_days) || days < 1 || days > 3650) e.delivery_days = "จำนวนวัน 1–3,650";

  const budgetErr = money(d.budget_amount);
  if (budgetErr) e.budget_amount = budgetErr;
  if (d.reference_price) {
    const refErr = money(d.reference_price);
    if (refErr) e.reference_price = refErr;
  }

  if (d.items.length === 0) e.items = "ต้องมีรายการพัสดุอย่างน้อย 1 รายการ";
  d.items.forEach((it, i) => {
    if (!it.description.trim()) e[`items.${i}.description`] = "กรอกรายละเอียด";
    if (!it.unit_th.trim()) e[`items.${i}.unit_th`] = "กรอกหน่วย";
    const qErr = money(it.quantity);
    if (qErr) e[`items.${i}.quantity`] = qErr;
    const pErr = money(it.unit_price, { allowZero: true });
    if (pErr) e[`items.${i}.unit_price`] = pErr;
  });

  // กฎวงเงิน (ตรวจเมื่อวงเงินอยู่ในรูปแบบถูกต้องแล้ว)
  const budget = toSatang(d.budget_amount);
  if (budget !== null && !e.budget_amount && method) {
    const min = method.min_budget_exclusive ? toSatang(method.min_budget_exclusive) : null;
    if (min !== null && budget <= min)
      e.budget_amount = `${method.name_th} ใช้กับวงเงินเกิน ${formatBaht(min)} บาท (พ.ร.บ. มาตรา 55, 56(2)(ข))`;
    const just = method.justifications.find((j) => String(j.id) === d.justification_id);
    const jMax = just?.max_budget_inclusive ? toSatang(just.max_budget_inclusive) : null;
    if (jMax !== null && budget > jMax)
      e.budget_amount = `เกินเพดาน ${formatBaht(jMax)} บาท ของ${just!.clause_ref}`;

    const total = itemsTotalExact(d.items);
    if (total !== null && total > budget * 100n && !e.items)
      e.items = `ยอดรวมรายการ ${formatBaht(exactToSatang(total))} บาท สูงกว่าวงเงินงบประมาณ (ระเบียบ ข้อ 22(4))`;
  }
  return e;
}

/** แปลง draft เป็น payload ของ POST /api/projects (เงินส่งเป็น string เพื่อให้ backend ได้ Decimal ตรงตัว) */
export function toProjectPayload(d: ProjectDraft, acknowledgeWarnings: boolean) {
  return {
    project_code: d.project_code.trim(),
    egp_project_no: d.egp_project_no || null,
    fiscal_year_be: Number(d.fiscal_year_be),
    title_th: d.title_th.trim(),
    reason_th: d.reason_th.trim(),
    department_id: Number(d.department_id),
    method_code: d.method_code,
    justification_id: d.justification_id ? Number(d.justification_id) : null,
    procurement_type: d.procurement_type,
    budget_amount: d.budget_amount,
    reference_price: d.reference_price || null,
    delivery_days: Number(d.delivery_days),
    items: d.items.map((it) => ({ ...it, description: it.description.trim(), unit_th: it.unit_th.trim() })),
    acknowledge_warnings: acknowledgeWarnings,
  };
}
