import { describe, expect, it } from "vitest";
import {
  currentFiscalYearBE, exactToSatang, formatBaht, itemsTotalExact, toProjectPayload, validateProjectDraft,
} from "./projectValidation";
import type { MethodInfo, ProjectDraft } from "./types";

const SPECIFIC: MethodInfo = {
  code: "SPECIFIC", category: "SPECIFIC", name_th: "วิธีเฉพาะเจาะจง", legal_basis: "มาตรา 55(3)",
  min_budget_exclusive: null, max_budget_inclusive: null,
  justifications: [
    { id: 8, clause_ref: "มาตรา 56(2)(ข)", description_th: "วงเงินไม่เกินที่กำหนดในกฎกระทรวง", max_budget_inclusive: "500000.00" },
    { id: 9, clause_ref: "มาตรา 56(2)(ค)", description_th: "ผู้ประกอบการรายเดียว", max_budget_inclusive: null },
  ],
};
const E_BIDDING: MethodInfo = {
  code: "E_BIDDING", category: "GENERAL_INVITATION", name_th: "e-bidding", legal_basis: "มาตรา 55(1)",
  min_budget_exclusive: "500000.00", max_budget_inclusive: null, justifications: [],
};

const valid = (over: Partial<ProjectDraft> = {}): ProjectDraft => ({
  project_code: "PSD-2570-002", egp_project_no: "", fiscal_year_be: "2570", title_th: "จัดซื้อครุภัณฑ์",
  reason_th: "เพื่อใช้ในราชการ", department_id: "1", method_code: "SPECIFIC", justification_id: "8",
  procurement_type: "GOODS", budget_amount: "100000.00", reference_price: "", delivery_days: "30",
  items: [{ description: "คอมพิวเตอร์", quantity: "4", unit_th: "เครื่อง", unit_price: "25000" }],
  ...over,
});

describe("validateProjectDraft (สะท้อน backend ProjectCreate + rule engine)", () => {
  it("accepts a valid specific-method draft", () => {
    expect(validateProjectDraft(valid(), SPECIFIC)).toEqual({});
  });

  it("enforces the 500,000 ceiling of มาตรา 56(2)(ข) exactly at the boundary", () => {
    const ok = valid({ budget_amount: "500000.00", items: [{ description: "x", quantity: "1", unit_th: "ชุด", unit_price: "500000" }] });
    expect(validateProjectDraft(ok, SPECIFIC)).toEqual({});
    const over = validateProjectDraft(valid({ budget_amount: "500000.01" }), SPECIFIC);
    expect(over.budget_amount).toContain("56(2)(ข)");
    // อนุมาตราอื่นไม่มีเพดาน
    expect(validateProjectDraft(valid({ budget_amount: "900000", justification_id: "9" }), SPECIFIC).budget_amount).toBeUndefined();
  });

  it("requires e-bidding budget above 500,000 and a justification for specific", () => {
    const e = validateProjectDraft(valid({ method_code: "E_BIDDING", justification_id: "", budget_amount: "500000" }), E_BIDDING);
    expect(e.budget_amount).toContain("500,000.00");
    expect(validateProjectDraft(valid({ justification_id: "" }), SPECIFIC).justification_id).toBeDefined();
  });

  it("flags item total above budget using exact (4-decimal) arithmetic", () => {
    // 3 × 33,333.34 = 100,000.02 > 100,000.00
    const e = validateProjectDraft(valid({ items: [{ description: "x", quantity: "3", unit_th: "ชุด", unit_price: "33333.34" }] }), SPECIFIC);
    expect(e.items).toContain("100,000.02");
    // 0.5 × 0.01 = 0.005 บาท → ไม่หายไปจากการปัดเศษ
    expect(itemsTotalExact([{ description: "", quantity: "0.5", unit_th: "", unit_price: "0.01" }])).toBe(50n);
  });

  it("validates formats of code, e-GP number, year and per-item fields", () => {
    const e = validateProjectDraft(valid({
      project_code: "psd 1", egp_project_no: "123", fiscal_year_be: "2559", delivery_days: "0",
      items: [{ description: "", quantity: "-1", unit_th: "", unit_price: "1,000" }],
    }), SPECIFIC);
    expect(Object.keys(e).sort()).toEqual([
      "delivery_days", "egp_project_no", "fiscal_year_be", "items.0.description", "items.0.quantity",
      "items.0.unit_price", "items.0.unit_th", "project_code",
    ]);
  });
});

describe("helpers", () => {
  it("formats baht and computes fiscal year", () => {
    expect(formatBaht(123456789n)).toBe("1,234,567.89");
    expect(formatBaht(exactToSatang(50n))).toBe("0.01");   // ปัดครึ่งขึ้น
    expect(currentFiscalYearBE(new Date(2026, 8, 30))).toBe(2569);
    expect(currentFiscalYearBE(new Date(2026, 9, 1))).toBe(2570);
  });

  it("builds a payload with money as strings and numeric ids", () => {
    const p = toProjectPayload(valid({ reference_price: "" }), true);
    expect(p).toMatchObject({ fiscal_year_be: 2570, department_id: 1, justification_id: 8, budget_amount: "100000.00",
                              reference_price: null, egp_project_no: null, acknowledge_warnings: true });
  });
});
