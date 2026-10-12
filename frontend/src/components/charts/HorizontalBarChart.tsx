/**
 * กราฟแท่งแนวนอน (เทียบขนาดระหว่างหมวด เช่น มูลค่าตามวิธีจัดหา)
 * ชื่อหมวดอยู่ที่แกน จึงไม่ต้องมี legend · ค่าแสดงที่ปลายแท่ง · แท่งหนาไม่เกิน 24px ปลายมน 4px
 */
import { useState } from "react";
import { compactBaht, fullBaht, rightRoundedRect, useElementWidth } from "./chartUtils";

export interface BarDatum { key: string; label: string; value: number; color: string; note?: string }

interface Props {
  data: BarDatum[];
  ariaLabel: string;
}

const ROW = 44;
const BAR = 20;
const LABEL_W = 108;
const VALUE_W = 76;

export function HorizontalBarChart({ data, ariaLabel }: Props) {
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const [hover, setHover] = useState<string | null>(null);
  const max = Math.max(...data.map((d) => d.value), 1);
  const trackW = Math.max(0, width - LABEL_W - VALUE_W);
  const height = data.length * ROW;
  const hovered = data.find((d) => d.key === hover);

  return (
    <div className="chart" ref={ref}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={ariaLabel} onMouseLeave={() => setHover(null)}>
          {data.map((d, i) => {
            const yTop = i * ROW + (ROW - BAR) / 2;
            const w = (d.value / max) * trackW;
            return (
              <g key={d.key} className={hover && hover !== d.key ? "dim" : ""}>
                <text className="cat" x={0} y={yTop + BAR / 2} dy="0.32em">{d.label}</text>
                <line className="grid" x1={LABEL_W} x2={LABEL_W} y1={i * ROW + 6} y2={(i + 1) * ROW - 6} />
                {w > 0 && <path d={rightRoundedRect(LABEL_W, yTop, w, BAR)} fill={d.color} />}
                <text className="value-label" x={LABEL_W + w + 8} y={yTop + BAR / 2} dy="0.32em">
                  {compactBaht(d.value)}
                </text>
                <rect className="hit" x={0} y={i * ROW} width={width} height={ROW} tabIndex={0}
                      aria-label={`${d.label} ${fullBaht(d.value)} บาท`}
                      onMouseEnter={() => setHover(d.key)} onFocus={() => setHover(d.key)} onBlur={() => setHover(null)} />
              </g>
            );
          })}
        </svg>
      )}
      {hovered && (
        <div className="tooltip" style={{ left: Math.max(0, Math.min(LABEL_W + 40, width - 220)),
                                           top: data.indexOf(hovered) * ROW + ROW - 4 }} role="status">
          <div className="tip-row">
            <span className="swatch" style={{ background: hovered.color }} />
            <strong>{hovered.label}</strong>
          </div>
          <div className="tip-row"><span /><span>มูลค่า</span><span className="num">{fullBaht(hovered.value)}</span></div>
          {hovered.note && <div className="tip-note">{hovered.note}</div>}
        </div>
      )}
    </div>
  );
}
