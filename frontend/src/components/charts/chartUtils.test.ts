import { describe, expect, it } from "vitest";
import { compactBaht, niceTicks, rightRoundedRect, topRoundedRect } from "./chartUtils";

describe("chartUtils", () => {
  it("produces round axis ticks that cover the max", () => {
    expect(niceTicks(18_684_056)).toEqual([0, 5_000_000, 10_000_000, 15_000_000, 20_000_000]);
    expect(niceTicks(0)).toEqual([0]);
    const t = niceTicks(730);
    expect(t[t.length - 1]).toBeGreaterThanOrEqual(730);
  });

  it("formats compact Thai baht labels", () => {
    expect(compactBaht(18_684_056)).toBe("18.7 ล้าน");
    expect(compactBaht(20_000_000)).toBe("20 ล้าน");
    expect(compactBaht(850_000)).toBe("850 พัน");
    expect(compactBaht(0)).toBe("0");
  });

  it("never draws a corner radius larger than the bar", () => {
    expect(topRoundedRect(0, 0, 20, 2)).toContain("V2");          // สูง 2px → รัศมี 2 ไม่ใช่ 4
    expect(rightRoundedRect(0, 0, 1, 20)).not.toContain("NaN");
  });
});
