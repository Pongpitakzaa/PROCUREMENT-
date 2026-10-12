/**
 * กราฟแท่งซ้อนแนวตั้ง (เช่น มูลค่ารายเดือน แยกตามวิธีจัดหา)
 * สเปก: แท่งกว้างไม่เกิน 24px · ปลายมน 4px ฐานเหลี่ยม · ช่องว่างสีพื้น 2px ระหว่างชั้น
 *       เส้นกริด 1px สีจาง · ป้ายค่าเฉพาะเดือนสูงสุด · tooltip เมื่อชี้/โฟกัสทั้งคอลัมน์
 */
import { useState } from "react";
import { compactBaht, fullBaht, niceTicks, topRoundedRect, useElementWidth } from "./chartUtils";

export interface Series { key: string; label: string; color: string }
export interface Category { key: string; label: string; fullLabel: string }

interface Props {
  categories: Category[];
  series: Series[];
  values: Record<string, Record<string, number>>;   // values[category][series]
  height?: number;
  ariaLabel: string;
}

const M = { top: 24, right: 8, bottom: 28, left: 52 };
const GAP = 2;
const TIP_W = 220;

export function StackedColumnChart({ categories, series, values, height = 280, ariaLabel }: Props) {
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);

  const totals = categories.map((c) => series.reduce((s, se) => s + (values[c.key]?.[se.key] ?? 0), 0));
  const ticks = niceTicks(Math.max(...totals, 0));
  const yMax = ticks[ticks.length - 1] || 1;
  const innerW = Math.max(0, width - M.left - M.right);
  const innerH = height - M.top - M.bottom;
  const band = categories.length ? innerW / categories.length : 0;
  const barW = Math.min(24, band * 0.6);
  const y = (v: number) => M.top + innerH - (v / yMax) * innerH;
  const peak = totals.indexOf(Math.max(...totals));

  const h = hover !== null ? categories[hover] : null;
  // tooltip วางข้างคอลัมน์ (ไม่บังแท่งที่กำลังดู): ขวาถ้าพอ ไม่งั้นซ้าย; จอแคบวางใต้กราฟแทน
  const narrow = width < 520;
  const tipX = hover !== null ? M.left + band * (hover + 0.5) : 0;
  const tipStyle = narrow ? undefined
    : tipX + barW / 2 + 12 + TIP_W <= width ? { left: tipX + barW / 2 + 12, top: M.top }
    : { left: tipX - barW / 2 - 12 - TIP_W, top: M.top };
  // ป้ายเดือนแสดงเว้นเดือนเมื่อพื้นที่ต่อคอลัมน์แคบ (ไม่ให้ตัวอักษรชนกัน)
  const labelEvery = band < 34 ? 2 : 1;

  return (
    <div className="chart" ref={ref}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={ariaLabel} onMouseLeave={() => setHover(null)}>
          {ticks.map((t) => (
            <g key={t}>
              <line className="grid" x1={M.left} x2={width - M.right} y1={y(t)} y2={y(t)} />
              <text className="tick" x={M.left - 8} y={y(t)} dy="0.32em" textAnchor="end">{compactBaht(t)}</text>
            </g>
          ))}
          {categories.map((c, i) => {
            const cx = M.left + band * (i + 0.5);
            const segs = series.map((s) => ({ s, v: values[c.key]?.[s.key] ?? 0 })).filter((x) => x.v > 0);
            let acc = 0;
            return (
              <g key={c.key} className={hover !== null && hover !== i ? "dim" : ""}>
                {segs.map(({ s, v }, k) => {
                  const y0 = y(acc);
                  acc += v;
                  const y1 = y(acc);
                  const isTop = k === segs.length - 1;
                  // ช่องว่าง 2px ที่ด้านบนของทุกชั้นที่มีชั้นอื่นซ้อนอยู่ด้านบน
                  const top = isTop ? y1 : y1 + GAP;
                  const hgt = Math.max(0, y0 - top);
                  return isTop
                    ? <path key={s.key} d={topRoundedRect(cx - barW / 2, top, barW, hgt)} fill={s.color} />
                    : <rect key={s.key} x={cx - barW / 2} y={top} width={barW} height={hgt} fill={s.color} />;
                })}
                {i === peak && totals[i]! > 0 && (
                  <text className="value-label" x={cx} y={y(totals[i]!) - 6} textAnchor="middle">{compactBaht(totals[i]!)}</text>
                )}
                {i % labelEvery === 0 && <text className="tick" x={cx} y={height - 8} textAnchor="middle">{c.label}</text>}
                {/* พื้นที่รับเมาส์/คีย์บอร์ดเต็มความกว้างคอลัมน์ (ใหญ่กว่าแท่งจริง) */}
                <rect className="hit" x={cx - band / 2} y={M.top} width={band} height={innerH} tabIndex={0}
                      aria-label={`${c.fullLabel} รวม ${fullBaht(totals[i]!)} บาท`}
                      onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)} onBlur={() => setHover(null)} />
              </g>
            );
          })}
          <line className="axis" x1={M.left} x2={width - M.right} y1={y(0)} y2={y(0)} />
        </svg>
      )}
      {h && hover !== null && (
        <div className={`tooltip ${narrow ? "below" : ""}`} style={tipStyle} role="status">
          <strong>{h.fullLabel}</strong>
          {series.map((s) => (
            <div key={s.key} className="tip-row">
              <span className="swatch" style={{ background: s.color }} />
              <span>{s.label}</span>
              <span className="num">{values[h.key]?.[s.key] ? fullBaht(values[h.key]![s.key]!) : "—"}</span>
            </div>
          ))}
          <div className="tip-row total"><span /><span>รวม</span><span className="num">{fullBaht(totals[hover]!)}</span></div>
        </div>
      )}
    </div>
  );
}
