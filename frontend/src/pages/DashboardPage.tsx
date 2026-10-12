/**
 * Dashboard สรุปผลการจัดซื้อจัดจ้างตามปีงบประมาณ
 * - KPI: จำนวนโครงการ / วงเงินงบประมาณ / มูลค่าที่อนุมัติสั่งซื้อ / ประหยัดงบประมาณ
 * - มูลค่าที่อนุมัติสั่งซื้อรายเดือน (ต.ค.–ก.ย.) แยกตามวิธีจัดหา + มุมมองตาราง
 * - สรุปตามวิธีจัดหา และตามสถานะโครงการ
 * สีของแต่ละวิธีผูกกับ "วิธี" เสมอ (ไม่เปลี่ยนตามลำดับ/ตัวกรอง) — ลำดับสีผ่านการตรวจ CVD แล้ว
 */
import { useEffect, useMemo, useState } from "react";
import { api, downloadDashboardReport } from "../api";
import { HorizontalBarChart } from "../components/charts/HorizontalBarChart";
import { StackedColumnChart, type Category, type Series } from "../components/charts/StackedColumnChart";
import { fullBaht } from "../components/charts/chartUtils";
import { StatusBadge } from "../components/StatusBadge";
import { currentFiscalYearBE } from "../projectValidation";
import type { DashboardSummary, MethodCode } from "../types";

/** ลำดับคงที่ = ลำดับซ้อนชั้นในกราฟ = ลำดับใน legend (ผ่าน validator: adjacent CVD ΔE ≥ 9.1) */
const METHOD_SERIES: (Series & { key: MethodCode })[] = [
  { key: "E_BIDDING", label: "e-bidding", color: "var(--series-1)" },
  { key: "E_MARKET", label: "e-market", color: "var(--series-2)" },
  { key: "SELECTION", label: "คัดเลือก", color: "var(--series-3)" },
  { key: "SPECIFIC", label: "เฉพาะเจาะจง", color: "var(--series-4)" },
];

const MONTH_SHORT = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."];
const MONTH_FULL = ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
                    "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"];

/** 12 เดือนของปีงบประมาณ: ต.ค. (ปีก่อน) – ก.ย. */
function fiscalMonths(fyBE: number): Category[] {
  const startCE = fyBE - 544;
  return [10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9].map((m) => {
    const yCE = m >= 10 ? startCE : startCE + 1;
    return { key: `${yCE}-${String(m).padStart(2, "0")}`, label: MONTH_SHORT[m - 1]!,
             fullLabel: `${MONTH_FULL[m - 1]} ${yCE + 543}` };
  });
}

const n = (v: string | number) => Number(v) || 0;
const pct = (part: number, whole: number) => (whole > 0 ? `${((part / whole) * 100).toFixed(1)}%` : "—");

export function DashboardPage() {
  const thisFY = currentFiscalYearBE();
  const [fy, setFy] = useState(thisFY);
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [asTable, setAsTable] = useState(false);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    setData(null);
    api<DashboardSummary>(`/api/dashboard/summary?fiscal_year=${fy}`)
      .then((d) => { setData(d); setError(null); })
      .catch((e: Error) => setError(e.message));
  }, [fy]);

  const months = useMemo(() => fiscalMonths(fy), [fy]);

  const view = useMemo(() => {
    if (!data) return null;
    const monthly: Record<string, Record<string, number>> = {};
    const byMethod = Object.fromEntries(METHOD_SERIES.map((s) => [s.key, {
      count: 0, budget: 0, awardCount: 0, award: 0, savings: 0,
    }])) as Record<MethodCode, { count: number; budget: number; awardCount: number; award: number; savings: number }>;
    for (const r of data.monthly_by_method) {
      (monthly[r.month] ??= {})[r.method_code] = n(r.award_total);
      const m = byMethod[r.method_code];
      m.awardCount += r.project_count;
      m.award += n(r.award_total);
      m.savings += n(r.savings_total);
    }
    const statusCount: Record<string, number> = {};
    for (const r of data.by_method_status) {
      byMethod[r.method_code].count += r.project_count;
      byMethod[r.method_code].budget += n(r.budget_total);
      statusCount[r.status] = (statusCount[r.status] ?? 0) + r.project_count;
    }
    const award = n(data.kpi.award_total);
    const savings = n(data.kpi.savings_total);
    return { monthly, byMethod, statusCount, award, savings, awardedBudget: award + savings,
             awardCount: data.monthly_by_method.reduce((s, r) => s + r.project_count, 0) };
  }, [data]);

  return (
    <section className="dashboard">
      <div className="page-head">
        <div>
          <h2>Dashboard สรุปผลการจัดซื้อจัดจ้าง</h2>
          <p className="muted">ปีงบประมาณ พ.ศ. {fy} (1 ต.ค. {fy - 1} – 30 ก.ย. {fy})</p>
        </div>
        <div className="head-actions">
          <select value={fy} onChange={(e) => setFy(Number(e.target.value))} aria-label="ปีงบประมาณ">
            {[thisFY, thisFY - 1, thisFY - 2, thisFY - 3].map((y) => <option key={y} value={y}>ปีงบประมาณ {y}</option>)}
          </select>
          <button type="button" className="ghost" disabled={exporting}
                  onClick={() => { setExporting(true); downloadDashboardReport(fy).catch((e: Error) => setError(e.message)).finally(() => setExporting(false)); }}>
            {exporting ? "กำลังสร้าง…" : "ดาวน์โหลด Excel"}
          </button>
        </div>
      </div>

      {error && <p role="alert" className="banner-error">{error}</p>}
      {!view && !error && <div className="card empty">กำลังโหลด…</div>}

      {view && data && (
        <>
          <div className="kpis">
            <div className="card kpi">
              <span className="kpi-label">โครงการทั้งหมด</span>
              <span className="kpi-value">{data.kpi.project_count.toLocaleString("th-TH")}</span>
              <span className="kpi-sub">อนุมัติสั่งซื้อ/จ้างแล้ว {view.awardCount.toLocaleString("th-TH")} โครงการ</span>
            </div>
            <div className="card kpi">
              <span className="kpi-label">วงเงินงบประมาณรวม</span>
              <span className="kpi-value">{fullBaht(n(data.kpi.budget_total))}</span>
              <span className="kpi-sub">บาท</span>
            </div>
            <div className="card kpi">
              <span className="kpi-label">มูลค่าที่อนุมัติสั่งซื้อ/จ้าง</span>
              <span className="kpi-value">{fullBaht(view.award)}</span>
              <span className="kpi-sub">บาท</span>
            </div>
            <div className="card kpi">
              <span className="kpi-label">ประหยัดงบประมาณ</span>
              <span className="kpi-value">{fullBaht(view.savings)}</span>
              <span className="kpi-sub">บาท · {pct(view.savings, view.awardedBudget)} ของวงเงินโครงการที่อนุมัติแล้ว</span>
            </div>
          </div>

          <div className="card chart-card">
            <div className="chart-head">
              <div>
                <h3>มูลค่าที่อนุมัติสั่งซื้อ/จ้าง รายเดือน</h3>
                <p className="muted small">แยกตามวิธีจัดหา (บาท) · นับตามวันที่อนุมัติสั่งซื้อ/สั่งจ้าง</p>
              </div>
              <div className="segmented" role="group" aria-label="รูปแบบการแสดงผล">
                <button type="button" className={!asTable ? "on" : ""} onClick={() => setAsTable(false)}>กราฟ</button>
                <button type="button" className={asTable ? "on" : ""} onClick={() => setAsTable(true)}>ตาราง</button>
              </div>
            </div>
            <ul className="legend">
              {METHOD_SERIES.map((s) => (
                <li key={s.key}><span className="swatch" style={{ background: s.color }} />{s.label}</li>
              ))}
            </ul>
            {view.awardCount === 0 ? (
              <div className="empty">ยังไม่มีโครงการที่อนุมัติสั่งซื้อ/จ้างในปีงบประมาณนี้</div>
            ) : asTable ? (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr><th>เดือน</th>{METHOD_SERIES.map((s) => <th key={s.key}>{s.label}</th>)}<th>รวม</th></tr>
                  </thead>
                  <tbody>
                    {months.map((m) => {
                      const row = view.monthly[m.key] ?? {};
                      const total = METHOD_SERIES.reduce((s, se) => s + (row[se.key] ?? 0), 0);
                      return (
                        <tr key={m.key}>
                          <th scope="row">{m.fullLabel}</th>
                          {METHOD_SERIES.map((s) => <td key={s.key}>{row[s.key] ? fullBaht(row[s.key]!) : "—"}</td>)}
                          <td className="strong">{total ? fullBaht(total) : "—"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <StackedColumnChart categories={months} series={METHOD_SERIES} values={view.monthly}
                                  ariaLabel={`มูลค่าที่อนุมัติสั่งซื้อรายเดือน ปีงบประมาณ ${fy}`} />
            )}
          </div>

          <div className="dash-grid">
            <div className="card chart-card">
              <h3>มูลค่าที่อนุมัติสั่งซื้อ/จ้าง ตามวิธีจัดหา</h3>
              <p className="muted small">บาท · ชี้ที่แท่งเพื่อดูรายละเอียด</p>
              <HorizontalBarChart
                ariaLabel="มูลค่าที่อนุมัติสั่งซื้อตามวิธีจัดหา"
                data={METHOD_SERIES.map((s) => ({
                  key: s.key, label: s.label, color: s.color, value: view.byMethod[s.key].award,
                  note: `${view.byMethod[s.key].awardCount} โครงการ · ประหยัด ${fullBaht(view.byMethod[s.key].savings)} บาท`,
                }))} />
              <div className="table-wrap">
                <table className="data-table compact">
                  <thead>
                    <tr><th>วิธี</th><th>โครงการ</th><th>วงเงินงบประมาณ</th><th>ประหยัด</th></tr>
                  </thead>
                  <tbody>
                    {METHOD_SERIES.map((s) => {
                      const m = view.byMethod[s.key];
                      return (
                        <tr key={s.key}>
                          <th scope="row"><span className="swatch" style={{ background: s.color }} />{s.label}</th>
                          <td>{m.count}</td>
                          <td>{fullBaht(m.budget)}</td>
                          <td>{pct(m.savings, m.award + m.savings)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="card chart-card">
              <h3>สถานะโครงการ</h3>
              <p className="muted small">จำนวนโครงการในปีงบประมาณ {fy}</p>
              {data.kpi.project_count === 0 ? (
                <div className="empty">ยังไม่มีโครงการ</div>
              ) : (
                <ul className="status-list">
                  {Object.entries(view.statusCount).sort((a, b) => b[1] - a[1]).map(([status, count]) => (
                    <li key={status}>
                      <StatusBadge status={status} />
                      <span className="status-bar"><span style={{ width: `${(count / data.kpi.project_count) * 100}%` }} /></span>
                      <span className="num">{count}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </>
      )}
    </section>
  );
}
