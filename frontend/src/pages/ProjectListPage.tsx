import { useEffect, useState } from "react";
import { api } from "../api";
import { PROJECT_STATUSES, StatusBadge, projectStatusTh } from "../components/StatusBadge";
import { currentFiscalYearBE } from "../projectValidation";
import type { MethodInfo, ProjectListItem, UpcomingDelivery } from "../types";
import { dueLabel, thaiDate } from "../deliveryText";

interface Props {
  methods: MethodInfo[];
  canCreate: boolean;
  onOpen: (projectId: number) => void;
  onCreate: () => void;
}

export function ProjectListPage({ methods, canCreate, onOpen, onCreate }: Props) {
  const [q, setQ] = useState("");
  const [fiscalYear, setFiscalYear] = useState(String(currentFiscalYearBE()));
  const [method, setMethod] = useState("");
  const [status, setStatus] = useState("");
  const [rows, setRows] = useState<ProjectListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [due, setDue] = useState<UpcomingDelivery[]>([]);

  useEffect(() => {
    api<UpcomingDelivery[]>("/api/deliveries/upcoming?within_days=14").then(setDue).catch(() => setDue([]));
  }, []);

  useEffect(() => {
    const params = new URLSearchParams();
    if (q.trim()) params.set("q", q.trim());
    if (fiscalYear) params.set("fiscal_year", fiscalYear);
    if (method) params.set("method", method);
    if (status) params.set("status", status);
    // หน่วงการค้นหาขณะพิมพ์ ไม่ยิง API ทุกตัวอักษร
    const t = setTimeout(() => {
      api<ProjectListItem[]>(`/api/projects?${params}`)
        .then((r) => { setRows(r); setError(null); })
        .catch((e: Error) => setError(e.message));
    }, 250);
    return () => clearTimeout(t);
  }, [q, fiscalYear, method, status]);

  const fy = currentFiscalYearBE();

  return (
    <section>
      <div className="page-head">
        <div>
          <h2>โครงการจัดซื้อจัดจ้าง</h2>
          <p className="muted">{rows ? `${rows.length} โครงการ` : "กำลังโหลด…"}</p>
        </div>
        {canCreate && <button type="button" onClick={onCreate}>+ สร้างโครงการใหม่</button>}
      </div>

      <div className="filters card">
        <input type="search" placeholder="ค้นหาชื่อหรือเลขที่โครงการ" value={q} onChange={(e) => setQ(e.target.value)}
               aria-label="ค้นหา" />
        <select value={fiscalYear} onChange={(e) => setFiscalYear(e.target.value)} aria-label="ปีงบประมาณ">
          <option value="">ทุกปีงบประมาณ</option>
          {[fy + 1, fy, fy - 1, fy - 2].map((y) => <option key={y} value={y}>ปีงบประมาณ {y}</option>)}
        </select>
        <select value={method} onChange={(e) => setMethod(e.target.value)} aria-label="วิธีจัดหา">
          <option value="">ทุกวิธี</option>
          {methods.map((m) => <option key={m.code} value={m.code}>{m.name_th}</option>)}
        </select>
        <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="สถานะ">
          <option value="">ทุกสถานะ</option>
          {PROJECT_STATUSES.map((s) => <option key={s} value={s}>{projectStatusTh(s)}</option>)}
        </select>
      </div>

      {error && <p role="alert" className="banner-error">{error}</p>}

      {due.length > 0 && (
        <section className="card due-panel" aria-label="ใกล้ครบกำหนดส่งมอบ">
          <h3>⏰ ใกล้ครบกำหนดส่งมอบ <small className="muted">({due.length} โครงการ ใน 14 วัน)</small></h3>
          <ul>
            {due.map((d) => (
              <li key={d.project_id} className={d.days_left < 0 ? "overdue" : d.days_left <= 3 ? "soon" : ""}>
                <button type="button" className="link" onClick={() => onOpen(d.project_id)}>
                  <b>{d.project_code}</b> {d.title_th}
                </button>
                <span className="due-when">{dueLabel(d.days_left)} · {thaiDate(d.due_date)}{d.source === "CONTRACT" ? " (ประมาณ)" : ""}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {rows && rows.length === 0 && (
        <div className="card empty">
          ไม่พบโครงการตามเงื่อนไข
          {canCreate && <><br /><button type="button" className="link" onClick={onCreate}>สร้างโครงการใหม่</button></>}
        </div>
      )}

      <ul className="project-list">
        {rows?.map((p) => {
          const pct = p.progress.total ? Math.round((p.progress.done / p.progress.total) * 100) : 0;
          return (
            <li key={p.project_id}>
              <button type="button" className="project-row card" onClick={() => onOpen(p.project_id)}>
                <div className="row-main">
                  <span className="code">{p.project_code}</span>
                  <span className="title">{p.title_th}</span>
                  <span className="meta">{p.method.name_th} · {p.department_name_th} · ปีงบประมาณ {p.fiscal_year_be}</span>
                </div>
                <div className="row-amount">
                  {Number(p.budget_amount).toLocaleString("th-TH", { minimumFractionDigits: 2 })}
                  <small>บาท</small>
                </div>
                <div className="row-progress">
                  <div className="progress" aria-label={`ความคืบหน้า ${pct}%`}><span style={{ width: `${pct}%` }} /></div>
                  <small>
                    {p.current_step ? `ขั้นที่ ${p.progress.done + 1}: ${p.current_step.name_th}` : "ครบทุกขั้นตอน"}
                  </small>
                </div>
                <StatusBadge status={p.status} />
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
