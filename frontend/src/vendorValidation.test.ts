import { describe, expect, it } from "vitest";
import type { VendorDraft } from "./types";
import { formatTaxId, guessVendorType, toVendorPayload, validateVendorDraft } from "./vendorValidation";

const d = (over: Partial<VendorDraft> = {}): VendorDraft => ({
  tax_id: "0105536092641", vendor_type: "JURISTIC", name_th: "บริษัท ตัวอย่าง จำกัด", address_th: "กรุงเทพฯ",
  phone: "", email: "", bank_account: "", ...over,
});

describe("vendorValidation (สะท้อน backend VendorCreate)", () => {
  it("accepts a valid juristic vendor", () => {
    expect(validateVendorDraft(d(), "create")).toEqual({});
  });

  it("checks tax id checksum and type/prefix consistency", () => {
    expect(validateVendorDraft(d({ tax_id: "0105536092642" }), "create").tax_id).toContain("checksum");
    expect(validateVendorDraft(d({ tax_id: "1234567890121" }), "create").tax_id).toContain("ขึ้นต้นด้วย 0");
    expect(validateVendorDraft(d({ tax_id: "0105536092641", vendor_type: "INDIVIDUAL" }), "create").tax_id).toContain("บุคคลธรรมดา");
    expect(validateVendorDraft(d({ tax_id: "" }), "edit").tax_id).toBeUndefined();    // แก้ไขไม่ตรวจเลข
  });

  it("validates optional contact fields only when filled", () => {
    const e = validateVendorDraft(d({ phone: "12345", email: "x@", bank_account: "12-34" }), "create");
    expect(Object.keys(e).sort()).toEqual(["bank_account", "email", "phone"]);
    expect(validateVendorDraft(d({ phone: "021234567", email: "a@b.co.th", bank_account: "1234567890" }), "create")).toEqual({});
  });

  it("formats and guesses", () => {
    expect(formatTaxId("0105536092641")).toBe("0-1055-36092-64-1");
    expect(guessVendorType("0105536092641")).toBe("JURISTIC");
    expect(guessVendorType("1234567890121")).toBe("INDIVIDUAL");
  });

  it("sends only changed fields on edit and keeps hidden contacts when blank", () => {
    const original = d({ email: "a@b.co.th" });
    expect(toVendorPayload(d({ email: "a@b.co.th" }), "edit", original)).toEqual({});
    expect(toVendorPayload(d({ email: "", phone: "0812345678" }), "edit", original))
      .toEqual({ email: null, phone: "0812345678" });
  });
});
