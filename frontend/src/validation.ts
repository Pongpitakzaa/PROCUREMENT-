/**
 * Client-side validation — ตรรกะเดียวกับ backend/app/rules/step_forms.py
 *
 * จุดประสงค์คือ UX (แจ้งผิดทันทีขณะกรอก) ไม่ใช่ความปลอดภัย:
 * backend ตรวจซ้ำทุกครั้งเสมอ เพราะ request สามารถถูกปลอมได้โดยไม่ผ่านหน้าจอนี้
 */
import type { FieldSpec, FormContext, FormValues } from "./types";

/** เลขประจำตัวผู้เสียภาษี 13 หลัก: หลักสุดท้าย = (11 - Σ d[i]*(13-i) mod 11) mod 10 */
export function isValidThaiTaxId(value: string): boolean {
  if (!/^\d{13}$/.test(value)) return false;
  let sum = 0;
  for (let i = 0; i < 12; i++) sum += Number(value[i]) * (13 - i);
  return (11 - (sum % 11)) % 10 === Number(value[12]);
}

const MONEY_RE = /^\d{1,13}(\.\d{1,2})?$/;

/**
 * แปลงเงินเป็น "สตางค์" แบบ BigInt — ห้ามใช้ Number/parseFloat เทียบเงิน
 * (0.1 + 0.2 !== 0.3 ทำให้เทียบวงเงินผิดได้ที่ขอบเพดาน เช่น 500,000.00)
 */
export function toSatang(value: string): bigint | null {
  if (!MONEY_RE.test(value)) return null;
  const [baht = "0", satang = ""] = value.split(".");
  return BigInt(baht) * 100n + BigInt(satang.padEnd(2, "0"));
}

export function isVisible(spec: FieldSpec, values: FormValues): boolean {
  return !spec.show_if || values[spec.show_if.field] === spec.show_if.equals;
}

function isEmpty(spec: FieldSpec, v: unknown): boolean {
  if (spec.type === "checkbox") return v !== true;
  return v === undefined || v === null || v === "" || (Array.isArray(v) && v.length === 0);
}

/** คืนข้อความผิดพลาดของช่องเดียว (หรือ null ถ้าผ่าน) */
export function validateField(spec: FieldSpec, values: FormValues): string | null {
  if (!isVisible(spec, values)) return null;
  const v = values[spec.name];

  if (isEmpty(spec, v)) {
    if (spec.type === "checkbox") return null;
    return spec.required || spec.show_if ? `กรุณากรอก${spec.label_th}` : null;
  }

  switch (spec.type) {
    case "text":
    case "textarea":
    case "select": {
      const s = String(v).trim();
      if (spec.max_length && s.length > spec.max_length) return `ยาวเกิน ${spec.max_length} ตัวอักษร`;
      if (spec.options && !spec.options.some((o) => o.value === s)) return "ไม่อยู่ในตัวเลือกที่กำหนด";
      return null;
    }
    case "money":
    case "percent": {
      const s = toSatang(String(v));
      if (s === null) return "ต้องเป็นตัวเลข ทศนิยมไม่เกิน 2 ตำแหน่ง (ไม่ใส่จุลภาค)";
      if (spec.min !== undefined && s < toSatang(spec.min.toFixed(2))!) return `ต้องไม่น้อยกว่า ${spec.min}`;
      if (spec.max !== undefined && s > toSatang(spec.max.toFixed(2))!) return `ต้องไม่เกิน ${spec.max}`;
      return null;
    }
    case "integer": {
      if (typeof v !== "number" || !Number.isInteger(v)) return "ต้องเป็นจำนวนเต็ม";
      if ((spec.min !== undefined && v < spec.min) || (spec.max !== undefined && v > spec.max))
        return `ต้องอยู่ระหว่าง ${spec.min} ถึง ${spec.max}`;
      return null;
    }
    case "date":
      return /^\d{4}-\d{2}-\d{2}$/.test(String(v)) && !Number.isNaN(Date.parse(String(v)))
        ? null : "รูปแบบวันที่ไม่ถูกต้อง";
    case "tax_id":
      return isValidThaiTaxId(String(v)) ? null : "เลขประจำตัวผู้เสียภาษี 13 หลักไม่ถูกต้อง (checksum ไม่ผ่าน)";
    case "personnel_multi":
    case "vendor_multi": {
      const arr = v as number[];
      if (new Set(arr).size !== arr.length) return "มีรายการซ้ำ";
      if (spec.min_items && arr.length < spec.min_items) return `ต้องเลือกอย่างน้อย ${spec.min_items} รายการ`;
      return null;
    }
    default:
      return null;
  }
}

/** ตรวจทั้งฟอร์ม + กฎข้ามช่อง + กฎระเบียบที่รู้ได้จากบริบทโครงการ */
export function validateForm(specs: FieldSpec[], values: FormValues, ctx: FormContext): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const spec of specs) {
    const err = validateField(spec, values);
    if (err) errors[spec.name] = err;
  }

  // lte_field เช่น ราคาที่ตกลง ≤ ราคาที่เสนอ
  for (const spec of specs) {
    if (!spec.lte_field || errors[spec.name] || errors[spec.lte_field]) continue;
    const a = toSatang(String(values[spec.name] ?? ""));
    const b = toSatang(String(values[spec.lte_field] ?? ""));
    if (a !== null && b !== null && a > b) errors[spec.name] = "ต้องไม่เกินราคาที่เสนอ";
  }

  const budget = toSatang(ctx.budget_amount)!;
  // ระเบียบ ข้อ 25: ผู้ตรวจรับคนเดียวได้เฉพาะวงเงินไม่เกิน 100,000 บาท
  const inspectors = values["inspection_committee"];
  if (Array.isArray(inspectors) && !errors["inspection_committee"]) {
    if (inspectors.length === 1 && budget > toSatang(ctx.small_purchase_max)!)
      errors["inspection_committee"] = "วงเงินเกิน 100,000 บาท ต้องแต่งตั้งคณะกรรมการตรวจรับอย่างน้อย 3 คน";
    else if (inspectors.length === 2) errors["inspection_committee"] = "คณะกรรมการตรวจรับต้องมีอย่างน้อย 3 คน";
  }

  // ระเบียบ ข้อ 57: ราคาที่จะสั่งซื้อ/ตกลง ต้องไม่เกินวงเงิน (เว้นแต่อนุมัติเงินเพิ่ม)
  for (const name of ["award_amount", "agreed_amount"]) {
    const amt = toSatang(String(values[name] ?? ""));
    if (amt !== null && !errors[name] && amt > budget && values["extra_budget_approved"] !== true)
      errors[name] = "สูงกว่าวงเงินงบประมาณ — ต้องต่อรองราคาหรือได้รับอนุมัติเงินเพิ่ม";
  }
  return errors;
}

/** ส่งเฉพาะช่องที่มองเห็น และส่งเงินเป็น string → ตรงกับที่ backend คาดหวัง */
export function toPayload(specs: FieldSpec[], values: FormValues): FormValues {
  const out: FormValues = {};
  for (const spec of specs) {
    if (!isVisible(spec, values)) continue;
    const v = values[spec.name];
    if (v === undefined || v === "") continue;
    out[spec.name] = typeof v === "string" ? v.trim() : v;
  }
  return out;
}
