import { describe, expect, it } from "vitest";
import { passwordProblems, roleProblems, USERNAME_RE } from "./userValidation";

describe("userValidation (สะท้อน backend security.py)", () => {
  it("password policy", () => {
    expect(passwordProblems("Correct-Horse-42")).toEqual([]);
    expect(passwordProblems("รหัสผ่านภาษาไทย2569")).toEqual([]);         // ตัวอักษรไทยนับเป็นตัวอักษร
    expect(passwordProblems("short1")).toHaveLength(1);
    expect(passwordProblems("officer2026abc", "officer")).toEqual(["ห้ามมีชื่อผู้ใช้อยู่ในรหัสผ่าน"]);
  });
  it("role segregation", () => {
    expect(roleProblems(["HEAD_OF_PROCUREMENT", "EXECUTIVE"])).toEqual([]);
    expect(roleProblems(["ADMIN", "PROCUREMENT_OFFICER"])).toHaveLength(1);
    expect(roleProblems(["AUDITOR", "ADMIN"])).toHaveLength(1);
    expect(roleProblems([])).toHaveLength(1);
  });
  it("username format", () => {
    expect(USERNAME_RE.test("somchai.j")).toBe(true);
    expect(USERNAME_RE.test("Somchai")).toBe(false);
    expect(USERNAME_RE.test("ab")).toBe(false);
  });
});
