import { describe, expect, it } from "vitest";
import { isIos } from "./pwa";

describe("isIos — เลือกวิธีติดตั้งแอป", () => {
  it("iPhone / iPad รุ่นเก่า", () => {
    expect(isIos("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X)", "iPhone", 5)).toBe(true);
    expect(isIos("Mozilla/5.0 (iPad; CPU OS 15_0 like Mac OS X)", "iPad", 5)).toBe(true);
  });
  it("iPadOS 13+ รายงานตัวเป็น Mac แต่มีจอสัมผัส", () => {
    expect(isIos("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)", "MacIntel", 5)).toBe(true);
  });
  it("Mac จริง / Android ไม่ใช่ iOS", () => {
    expect(isIos("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)", "MacIntel", 0)).toBe(false);
    expect(isIos("Mozilla/5.0 (Linux; Android 14; Pixel 7)", "Linux armv81", 5)).toBe(false);
  });
});
