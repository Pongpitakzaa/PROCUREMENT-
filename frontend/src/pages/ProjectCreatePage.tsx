/**
 * หน้าสร้างโครงการ
 * - ตรวจข้อมูลทันทีฝั่ง client (projectValidation.ts) เมื่อผู้ใช้ออกจากช่อง/กดบันทึก
 * - เมื่อข้อมูลผ่านขั้นต้นแล้ว เรียก POST /api/projects/validate (dry-run) เพื่อรับผลตรวจตามระเบียบ
 *   ที่ต้องใช้ข้อมูลในฐานข้อมูล เช่น สงสัยแบ่งซื้อแบ่งจ้าง / ราคากลางเกินวงเงิน (WARNING)
 * - แสดงลำดับขั้นตอนที่จะเกิดขึ้นจริงตามวิธี + วงเงิน (GET /api/workflow/{method})
 */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { ApiError, api } from "../api";
import {
  currentFiscalYearBE, emptyItem, exactToSatang, formatBaht, itemsTotalExact, toProjectPayload,
  validateProjectDraft,
} from "../projectValidation";
import type { Department, ItemDraft, MethodInfo, ProjectDraft, Violation, WorkflowPreviewStep } from "../types";
import { toSatang } from "../validation";

const PROCUREMENT_TYPES = [
  { value: "GOODS", label: "ซื้อ (วัสดุ/ครุภัณฑ์)" },
  { value: "SERVICE", label: "จ้างทำของ/จ้างบริการ" },
  { value: "CONSTRUCTION", label: "จ้างก่อสร้าง" },
  { value: "CONSULTANT", label: "จ้างที่ปรึกษา" },
  { value: "DESIGN", label: "จ้างออกแบบและควบคุมงาน" },
];

interface Props {
  methods: MethodInfo[];
  onCreated: (projectId: number) => void;
  onCancel: () => void;
}

export function ProjectCreatePage({ methods, onCreated, onCancel }: Props) {
  const [departments, setDepartments] = useState<Department[]>([]);
  const [draft, setDraft] = useState<ProjectDraft>(() => ({
    project_code: "", egp_project_no: "", fiscal_year_be: String(currentFiscalYearBE()), title_th: "",
    reason_th: "", department_id: "", method_code: "", justification_id: "", procurement_type: "GOODS",
    budget_amount: "", reference_price: "", delivery_days: "30", items: [emptyItem()],
  }));
  const [touched, setTouched] = useState<Set<string>>(new Set());
  const [showAll, setShowAll] = useState(false);
  const [serverViolations, setServerViolations] = useState<Violation[]>([]);
  const [checking, setChecking] = useState(false);
  const [workflow, setWorkflow] = useState<WorkflowPreviewStep[]>([]);
  const [acknowledge, setAcknowledge] = useState(false);
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState<string | null>(null);

  useEffect(() => {
    api<Department[]>("/api/departments").then((ds) => {
      setDepartments(ds);
      if (ds.length === 1) setDraft((d) => ({ ...d, department_id: String(ds[0]!.department_id) }));
    });
  }, []);

  const method = methods.find((m) => m.code === draft.method_code);
  const errors = useMemo(() => validateProjectDraft(draft, method), [draft, method]);
  const clientValid = Object.keys(errors).length === 0;
  const budgetSatang = errors.budget_amount ? null : toSatang(draft.budget_amount);

  // ผลตรวจตามระเบียบจากเซิร์ฟเวอร์ (dry-run) เมื่อข้อมูลผ่านขั้นต้นแล้ว
  useEffect(() => {
    if (!clientValid) { setServerViolations([]); return; }
    setChecking(true);
    const t = setTimeout(() => {
      api<{ violations: Violation[] }>("/api/projects/validate", {
        method: "POST", body: JSON.stringify(toProjectPayload(draft, false)),
      })
        .then((r) => setServerViolations(r.violations))
        .catch((e) => setServerViolations(e instanceof ApiError ? e.violations : []))
        .finally(() => setChecking(false));
    }, 600);
    return () => clearTimeout(t);
  }, [draft, clientValid]);

  // ลำดับขั้นตอนตามวิธี + วงเงิน
  useEffect(() => {
    if (!draft.method_code || budgetSatang === null || budgetSatang <= 0n) { setWorkflow([]); return; }
    const t = setTimeout(() => {
      api<WorkflowPreviewStep[]>(`/api/workflow/${draft.method_code}?budget=${encodeURIComponent(draft.budget_amount)}`)
        .then(setWorkflow).catch(() => setWorkflow([]));
    }, 300);
    return () => clearTimeout(t);
  }, [draft.method_code, draft.budget_amount, budgetSatang]);

  const set = <K extends keyof ProjectDraft>(key: K, value: ProjectDraft[K]) => {
    setDraft((d) => ({ ...d, [key]: value }));
    setAcknowledge(false);   // ข้อมูลเปลี่ยน → ต้องยืนยันคำเตือนใหม่
  };
  const setItem = (i: number, key: keyof ItemDraft, value: string) =>
    set("items", draft.items.map((it, idx) => (idx === i ? { ...it, [key]: value } : it)));
  const touch = (key: string) => setTouched((t) => new Set(t).add(key));
  const errorOf = (key: string) =>
    // คำเตือน (WARNING) แสดงที่แผงด้านขวาเท่านั้น ไม่แสดงเป็นข้อผิดพลาดสีแดงที่ช่องกรอก
    showAll || touched.has(key)
      ? errors[key] ?? serverViolations.find((v) => v.field === key && v.severity === "ERROR")?.message
      : undefined;

  const serverErrors = serverViolations.filter((v) => v.severity === "ERROR");
  const warnings = serverViolations.filter((v) => v.severity === "WARNING");
  const itemsTotal = itemsTotalExact(draft.items);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setShowAll(true);
    setBanner(null);
    if (!clientValid || serverErrors.length > 0) {
      setBanner("กรุณาแก้ไขข้อมูลที่ไม่ถูกต้องก่อนบันทึก");
      return;
    }
    if (warnings.length > 0 && !acknowledge) {
      setBanner("มีคำเตือนตามระเบียบ กรุณาอ่านและติ๊กยืนยันก่อนบันทึก");
      return;
    }
    setBusy(true);
    try {
      const r = await api<{ project_id: number }>("/api/projects", {
        method: "POST", body: JSON.stringify(toProjectPayload(draft, acknowledge)),
      });
      onCreated(r.project_id);
    } catch (err) {
      if (err instanceof ApiError) {
        setServerViolations(err.violations);
        setBanner(err.message);
      } else setBanner("เชื่อมต่อเซิร์ฟเวอร์ไม่ได้");
    } finally {
      setBusy(false);
    }
  }

  const field = (key: keyof ProjectDraft | string, label: string, input: ReactNode,
                 opts: { required?: boolean; help?: string; wide?: boolean } = {}) => (
    <div className={`field ${opts.wide ? "wide" : ""} ${errorOf(key) ? "has-error" : ""}`}>
      <label htmlFor={`p-${key}`}>{label}{opts.required !== false && <span aria-hidden> *</span>}</label>
      {input}
      {opts.help && <small className="help">{opts.help}</small>}
      {errorOf(key) && <small role="alert" className="error">{errorOf(key)}</small>}
    </div>
  );

  const text = (key: keyof ProjectDraft, extra: React.InputHTMLAttributes<HTMLInputElement> = {}) => (
    <input id={`p-${key}`} value={draft[key] as string} onBlur={() => touch(key)}
           onChange={(e) => set(key, e.target.value as never)} {...extra} />
  );

  return (
    <section>
      <button type="button" className="link" onClick={onCancel}>← รายการโครงการ</button>
      <div className="page-head"><h2>สร้างโครงการใหม่</h2></div>

      <form className="create-layout" onSubmit={submit} noValidate>
        <div className="create-main">
          {banner && <div role="alert" className="banner-error">{banner}</div>}

          {/* 1) ข้อมูลทั่วไป */}
          <fieldset className="card section">
            <legend>1. ข้อมูลโครงการ</legend>
            <div className="grid-2">
              {field("project_code", "เลขที่โครงการ (ภายในหน่วยงาน)",
                text("project_code", { placeholder: "PSD-2570-002",
                  onChange: (e) => set("project_code", e.target.value.toUpperCase()) }))}
              {field("egp_project_no", "เลขโครงการในระบบ e-GP",
                text("egp_project_no", { inputMode: "numeric", maxLength: 11, placeholder: "ถ้ามี (11 หลัก)",
                  onChange: (e) => set("egp_project_no", e.target.value.replace(/\D/g, "")) }),
                { required: false })}
              {field("fiscal_year_be", "ปีงบประมาณ (พ.ศ.)", text("fiscal_year_be", { inputMode: "numeric", maxLength: 4 }))}
              {field("department_id", "หน่วยงานเจ้าของโครงการ", (
                <select id="p-department_id" value={draft.department_id} onBlur={() => touch("department_id")}
                        onChange={(e) => set("department_id", e.target.value)}>
                  <option value="">— เลือก —</option>
                  {departments.map((d) => <option key={d.department_id} value={d.department_id}>{d.name_th}</option>)}
                </select>
              ))}
            </div>
            {field("title_th", "ชื่อโครงการ", text("title_th", { maxLength: 500, placeholder: "เช่น จัดซื้อครุภัณฑ์คอมพิวเตอร์ จำนวน 5 เครื่อง" }), { wide: true })}
            {field("reason_th", "เหตุผลความจำเป็นที่ต้องซื้อหรือจ้าง", (
              <textarea id="p-reason_th" rows={3} maxLength={5000} value={draft.reason_th}
                        onBlur={() => touch("reason_th")} onChange={(e) => set("reason_th", e.target.value)} />
            ), { wide: true, help: "ระเบียบ ข้อ 22(1)" })}
          </fieldset>

          {/* 2) วิธีจัดหาและวงเงิน */}
          <fieldset className="card section">
            <legend>2. วิธีจัดหาและวงเงิน</legend>
            {field("procurement_type", "ประเภทพัสดุ", (
              <div className="chips" role="radiogroup" id="p-procurement_type">
                {PROCUREMENT_TYPES.map((t) => (
                  <label key={t.value} className={`chip ${draft.procurement_type === t.value ? "on" : ""}`}>
                    <input type="radio" name="procurement_type" value={t.value}
                           checked={draft.procurement_type === t.value}
                           onChange={() => set("procurement_type", t.value)} />
                    {t.label}
                  </label>
                ))}
              </div>
            ), { wide: true })}

            {field("method_code", "วิธีจัดหา", (
              <div className="method-cards" role="radiogroup" id="p-method_code">
                {methods.map((m) => (
                  <label key={m.code} className={`method-card ${draft.method_code === m.code ? "on" : ""}`}>
                    <input type="radio" name="method_code" value={m.code} checked={draft.method_code === m.code}
                           onChange={() => { set("method_code", m.code); set("justification_id", ""); touch("method_code"); }} />
                    <strong>{m.name_th}</strong>
                    <small>{m.legal_basis}</small>
                    {m.min_budget_exclusive && <small>วงเงินเกิน {Number(m.min_budget_exclusive).toLocaleString("th-TH")} บาท</small>}
                  </label>
                ))}
              </div>
            ), { wide: true, help: "พ.ร.บ.การจัดซื้อจัดจ้างฯ พ.ศ. 2560 มาตรา 55" })}

            {method && method.category !== "GENERAL_INVITATION" && field("justification_id", "เหตุผลที่ใช้วิธีนี้ (มาตรา 56)", (
              <select id="p-justification_id" value={draft.justification_id}
                      onBlur={() => touch("justification_id")} onChange={(e) => set("justification_id", e.target.value)}>
                <option value="">— เลือกอนุมาตรา —</option>
                {method.justifications.map((j) => (
                  <option key={j.id} value={j.id}>
                    {j.clause_ref} {j.description_th}
                    {j.max_budget_inclusive ? ` (ไม่เกิน ${Number(j.max_budget_inclusive).toLocaleString("th-TH")} บาท)` : ""}
                  </option>
                ))}
              </select>
            ), { wide: true })}

            <div className="grid-3">
              {field("budget_amount", "วงเงินงบประมาณ (บาท)",
                text("budget_amount", { inputMode: "decimal", placeholder: "0.00",
                  onChange: (e) => set("budget_amount", e.target.value.replace(/,/g, "")) }),
                { help: budgetSatang !== null && budgetSatang > 0n ? `${formatBaht(budgetSatang)} บาท` : undefined })}
              {field("reference_price", "ราคากลาง (บาท)",
                text("reference_price", { inputMode: "decimal", placeholder: "ถ้ามี",
                  onChange: (e) => set("reference_price", e.target.value.replace(/,/g, "")) }),
                { required: false, help: "กรอกภายหลังในรายงานขอซื้อได้" })}
              {field("delivery_days", "กำหนดส่งมอบ (วัน)", text("delivery_days", { inputMode: "numeric" }),
                { help: "ระเบียบ ข้อ 22(5)" })}
            </div>
          </fieldset>

          {/* 3) รายการพัสดุ */}
          <fieldset className="card section">
            <legend>3. รายการพัสดุ</legend>
            <div className="items">
              <div className="items-head" aria-hidden>
                <span>#</span><span>รายละเอียด</span><span>จำนวน</span><span>หน่วย</span><span>ราคา/หน่วย</span><span>รวม</span><span />
              </div>
              {draft.items.map((it, i) => {
                const q = toSatang(it.quantity);
                const p = toSatang(it.unit_price);
                const line = q !== null && p !== null ? formatBaht(exactToSatang(q * p)) : "—";
                const cell = (key: keyof ItemDraft, label: string, extra: React.InputHTMLAttributes<HTMLInputElement> = {}) => {
                  const k = `items.${i}.${key}`;
                  return (
                    <span className={errorOf(k) ? "has-error" : ""}>
                      <input aria-label={`${label} รายการที่ ${i + 1}`} value={it[key]} onBlur={() => touch(k)}
                             onChange={(e) => setItem(i, key, e.target.value)} title={errorOf(k)} {...extra} />
                      {errorOf(k) && <small className="error">{errorOf(k)}</small>}
                    </span>
                  );
                };
                return (
                  <div className="item-row" key={i}>
                    <span className="no">{i + 1}</span>
                    {cell("description", "รายละเอียด", { placeholder: "รายละเอียดพัสดุ" })}
                    {cell("quantity", "จำนวน", { inputMode: "decimal" })}
                    {cell("unit_th", "หน่วย", { placeholder: "เครื่อง" })}
                    {cell("unit_price", "ราคาต่อหน่วย", { inputMode: "decimal",
                      onChange: (e) => setItem(i, "unit_price", e.target.value.replace(/,/g, "")) })}
                    <span className="line-total">{line}</span>
                    <button type="button" className="ghost icon" disabled={draft.items.length === 1}
                            aria-label={`ลบรายการที่ ${i + 1}`}
                            onClick={() => set("items", draft.items.filter((_, idx) => idx !== i))}>✕</button>
                  </div>
                );
              })}
            </div>
            <div className="items-foot">
              <button type="button" className="ghost" disabled={draft.items.length >= 500}
                      onClick={() => set("items", [...draft.items, emptyItem()])}>+ เพิ่มรายการ</button>
              <div className={`items-total ${errors.items && (showAll || touched.size > 0) ? "over" : ""}`}>
                รวมทั้งสิ้น <strong>{itemsTotal !== null ? formatBaht(exactToSatang(itemsTotal)) : "—"}</strong> บาท
                {budgetSatang !== null && <small> / วงเงิน {formatBaht(budgetSatang)} บาท</small>}
              </div>
            </div>
            {errorOf("items") && <p role="alert" className="error">{errorOf("items")}</p>}
          </fieldset>
        </div>

        {/* แผงด้านขวา: ผลตรวจตามระเบียบ + ขั้นตอนที่จะเกิดขึ้น + ปุ่มบันทึก */}
        <aside className="create-side">
          <div className="card panel">
            <h3>ตรวจสอบตามระเบียบ</h3>
            {!clientValid ? (
              <p className="muted">กรอกข้อมูลให้ครบถ้วนและถูกต้อง ({Object.keys(errors).length} รายการที่ยังต้องแก้)</p>
            ) : checking ? (
              <p className="muted">กำลังตรวจสอบ…</p>
            ) : serverViolations.length === 0 ? (
              <p className="ok-text">✓ ผ่านการตรวจสอบเบื้องต้น</p>
            ) : (
              <ul className="violations">
                {serverViolations.map((v, i) => (
                  <li key={i} className={v.severity === "WARNING" ? "warn" : "err"}>
                    <strong>{v.severity === "WARNING" ? "คำเตือน" : "ข้อผิดพลาด"}</strong> {v.message}
                    {v.legal_ref && <small>อ้างอิง: {v.legal_ref}</small>}
                  </li>
                ))}
              </ul>
            )}
            {warnings.length > 0 && serverErrors.length === 0 && (
              <label className="ack">
                <input type="checkbox" checked={acknowledge} onChange={(e) => setAcknowledge(e.target.checked)} />
                รับทราบคำเตือนและยืนยันดำเนินการต่อ
              </label>
            )}
          </div>

          {workflow.length > 0 && (
            <div className="card panel">
              <h3>ขั้นตอนที่จะดำเนินการ</h3>
              <ol className="preview-steps">
                {workflow.map((s) => (
                  <li key={s.code}>
                    {s.name_th}
                    {s.document && <small>เอกสาร: {s.document}</small>}
                  </li>
                ))}
              </ol>
              {workflow[0]?.min_announce_working_days && (
                <p className="muted small">ระยะเวลาประกาศขั้นต่ำ {workflow[0].min_announce_working_days} วันทำการ (ระเบียบ ข้อ 46)</p>
              )}
            </div>
          )}

          <button type="submit" className="submit" disabled={busy}>{busy ? "กำลังบันทึก…" : "บันทึกโครงการ"}</button>
          <button type="button" className="ghost" onClick={onCancel}>ยกเลิก</button>
        </aside>
      </form>
    </section>
  );
}
