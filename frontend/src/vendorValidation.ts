/**
 * ตรวจฟอร์มผู้ประกอบการฝั่ง client — สะท้อน backend/app/schemas.py (VendorCreate / VendorUpdate)
 */
import type { VendorDraft } from "./types";
import { isValidThaiTaxId } from "./validation";

export type VendorErrors = Partial<Record<keyof VendorDraft, string>>;

/** แสดงเลข 13 หลักแบบ X-XXXX-XXXXX-XX-X */
export function formatTaxId(v: string): string {
  return /^\d{13}$/.test(v) ? `${v[0]}-${v.slice(1, 5)}-${v.slice(5, 10)}-${v.slice(10, 12)}-${v[12]}` : v;
}

/** เดาประเภทจากเลข: นิติบุคคลขึ้นต้นด้วย 0 (กรมพัฒนาธุรกิจการค้า) */
export const guessVendorType = (taxId: string) => (taxId.startsWith("0") ? "JURISTIC" : "INDIVIDUAL");

/**
 * mode "create": ทุกช่องบังคับตาม schema · mode "edit": ไม่มีเลขผู้เสียภาษี และช่องเบอร์/บัญชีว่าง = ไม่เปลี่ยน
 */
export function validateVendorDraft(d: VendorDraft, mode: "create" | "edit"): VendorErrors {
  const e: VendorErrors = {};
  if (mode === "create") {
    if (!/^\d{13}$/.test(d.tax_id)) e.tax_id = "ต้องเป็นตัวเลข 13 หลัก";
    else if (!isValidThaiTaxId(d.tax_id)) e.tax_id = "เลขไม่ถูกต้อง (checksum ไม่ผ่าน) กรุณาตรวจสอบอีกครั้ง";
    else if (d.vendor_type === "JURISTIC" && !d.tax_id.startsWith("0")) e.tax_id = "เลขทะเบียนนิติบุคคลต้องขึ้นต้นด้วย 0";
    else if (d.vendor_type === "INDIVIDUAL" && d.tax_id.startsWith("0")) e.tax_id = "บุคคลธรรมดาให้ใช้เลขประจำตัวประชาชน";
  }
  if (!d.name_th.trim()) e.name_th = "กรุณากรอกชื่อผู้ประกอบการ";
  else if (d.name_th.length > 500) e.name_th = "ยาวเกิน 500 ตัวอักษร";
  if (!d.address_th.trim()) e.address_th = "กรุณากรอกที่อยู่";
  if (d.phone && !/^0\d{8,9}$/.test(d.phone)) e.phone = "เบอร์โทร 9–10 หลัก ขึ้นต้นด้วย 0 (ไม่มีขีด)";
  if (d.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(d.email)) e.email = "รูปแบบอีเมลไม่ถูกต้อง";
  if (d.bank_account && !/^\d{10,15}$/.test(d.bank_account)) e.bank_account = "เลขบัญชี 10–15 หลัก (ตัวเลขเท่านั้น)";
  return e;
}

/** payload สำหรับ POST (สร้าง) หรือ PATCH (แก้ไข — ส่งเฉพาะช่องที่เปลี่ยน) */
export function toVendorPayload(d: VendorDraft, mode: "create" | "edit", original?: VendorDraft) {
  const clean = {
    name_th: d.name_th.trim(),
    address_th: d.address_th.trim(),
    email: d.email.trim() || null,
    phone: d.phone || null,
    bank_account: d.bank_account || null,
  };
  if (mode === "create") return { tax_id: d.tax_id, vendor_type: d.vendor_type, ...clean };
  const out: Record<string, string | null> = {};
  if (clean.name_th !== original?.name_th) out.name_th = clean.name_th;
  if (clean.address_th !== original?.address_th) out.address_th = clean.address_th;
  if (clean.email !== (original?.email || null)) out.email = clean.email;
  if (d.phone) out.phone = d.phone;                  // ว่าง = คงค่าเดิม (ค่าเดิมเห็นได้เฉพาะแบบปิดบัง)
  if (d.bank_account) out.bank_account = d.bank_account;
  return out;
}
