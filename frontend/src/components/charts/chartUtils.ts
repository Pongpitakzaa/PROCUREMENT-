import { useEffect, useRef, useState } from "react";

/** ความกว้างจริงของกล่อง (ใช้ทำกราฟ SVG แบบ responsive) */
export function useElementWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setWidth(entry!.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width] as const;
}

/** ค่าขีดแกนแบบตัวเลขกลม ๆ (1, 2, 2.5, 5 × 10^n) */
export function niceTicks(max: number, count = 4): number[] {
  if (max <= 0) return [0];
  const raw = max / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = ([1, 2, 2.5, 5, 10].find((m) => m * mag >= raw) ?? 10) * mag;
  const ticks = [];
  for (let v = 0; v <= max + step * 0.0001; v += step) ticks.push(v);
  if (ticks[ticks.length - 1]! < max) ticks.push(ticks[ticks.length - 1]! + step);
  return ticks;
}

/** ย่อจำนวนเงินสำหรับแกน/ป้าย: 12.5 ล้าน, 850 พัน */
export function compactBaht(v: number): string {
  if (v >= 1_000_000) return `${trim(v / 1_000_000)} ล้าน`;
  if (v >= 1_000) return `${trim(v / 1_000)} พัน`;
  return trim(v);
}

const trim = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(1).replace(/\.0$/, ""));

export const fullBaht = (v: number) => v.toLocaleString("th-TH", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** สี่เหลี่ยมที่มนเฉพาะด้านปลายข้อมูล (บน) 4px ฐานเหลี่ยม — ตามสเปกแท่งกราฟ */
export function topRoundedRect(x: number, y: number, w: number, h: number, r = 4): string {
  const rr = Math.min(r, h, w / 2);
  return `M${x},${y + h}V${y + rr}Q${x},${y} ${x + rr},${y}H${x + w - rr}Q${x + w},${y} ${x + w},${y + rr}V${y + h}Z`;
}

/** สี่เหลี่ยมที่มนเฉพาะปลายขวา (แท่งแนวนอน) */
export function rightRoundedRect(x: number, y: number, w: number, h: number, r = 4): string {
  const rr = Math.min(r, w, h / 2);
  return `M${x},${y}H${x + w - rr}Q${x + w},${y} ${x + w},${y + rr}V${y + h - rr}Q${x + w},${y + h} ${x + w - rr},${y + h}H${x}Z`;
}
