import { describe, expect, it } from "vitest";
import type { FieldSpec, FormContext } from "./types";
import { isValidThaiTaxId, toPayload, toSatang, validateForm } from "./validation";

const ctx: FormContext = { budget_amount: "80000.00", method: "SPECIFIC", small_purchase_max: "100000" };

const priceForm: FieldSpec[] = [
  { name: "vendor_tax_id", label_th: "เลขผู้เสียภาษี", type: "tax_id", required: true },
  { name: "quoted_amount", label_th: "ราคาที่เสนอ", type: "money", required: true, min: 0.01 },
  { name: "agreed_amount", label_th: "ราคาที่ตกลง", type: "money", required: true, min: 0.01, lte_field: "quoted_amount" },
];

describe("validation (ต้องตรงกับ backend/app/rules)", () => {
  it("checks the 13-digit tax id checksum", () => {
    expect(isValidThaiTaxId("0105536092641")).toBe(true);
    expect(isValidThaiTaxId("0105536092642")).toBe(false);
    expect(isValidThaiTaxId("010553609264")).toBe(false);
  });

  it("compares money exactly in satang, not floats", () => {
    expect(toSatang("500000.00")).toBe(50000000n);
    expect(toSatang("0.1")! + toSatang("0.2")!).toBe(toSatang("0.3"));
    expect(toSatang("1,000")).toBeNull();
    expect(toSatang("1.234")).toBeNull();
  });

  it("flags cross-field and budget rules", () => {
    const errs = validateForm(priceForm, {
      vendor_tax_id: "0105536092641", quoted_amount: "70000", agreed_amount: "75000",
    }, ctx);
    expect(errs.agreed_amount).toContain("ไม่เกินราคาที่เสนอ");

    const over = validateForm(priceForm, {
      vendor_tax_id: "0105536092641", quoted_amount: "90000", agreed_amount: "85000",
    }, ctx);
    expect(over.agreed_amount).toContain("สูงกว่าวงเงิน");
  });

  it("enforces sole-inspector limit (ระเบียบ ข้อ 25)", () => {
    const spec: FieldSpec[] = [{ name: "inspection_committee", label_th: "ผู้ตรวจรับ", type: "personnel_multi", required: true, min_items: 1 }];
    expect(validateForm(spec, { inspection_committee: [1] }, ctx)).toEqual({});
    expect(validateForm(spec, { inspection_committee: [1] }, { ...ctx, budget_amount: "150000" }).inspection_committee)
      .toContain("อย่างน้อย 3 คน");
  });

  it("requires show_if fields only when visible, and omits hidden ones from payload", () => {
    const spec: FieldSpec[] = [
      { name: "extra_budget_approved", label_th: "อนุมัติเงินเพิ่ม", type: "checkbox", required: false },
      { name: "extra_budget_ref", label_th: "เลขที่หนังสือ", type: "text", required: true, show_if: { field: "extra_budget_approved", equals: true } },
    ];
    expect(validateForm(spec, {}, ctx)).toEqual({});
    expect(validateForm(spec, { extra_budget_approved: true }, ctx).extra_budget_ref).toBeDefined();
    expect(toPayload(spec, { extra_budget_approved: false, extra_budget_ref: "x" })).toEqual({ extra_budget_approved: false });
  });
});
