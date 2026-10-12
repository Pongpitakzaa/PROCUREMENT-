/**
 * ทะเบียนผู้ประกอบการ (master–detail)
 * - ซ้าย: รายการ + ค้นหา/กรอง (ประเภท, ผู้ทิ้งงาน) + สถิติการเสนอราคา
 * - ขวา: รายละเอียด (ข้อมูลติดต่อแสดงแบบปิดบังเท่านั้น), ประวัติโครงการ, บัญชีผู้ทิ้งงาน
 *        หรือฟอร์มลงทะเบียน/แก้ไข
 * บนมือถือแสดงทีละส่วน (รายการ → รายละเอียด) พร้อมปุ่มย้อนกลับ
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, api } from "../api";
import { fullBaht } from "../components/charts/chartUtils";
import type { Violation, VendorDetail, VendorDraft, VendorListItem } from "../types";
import { formatTaxId, guessVendorType, toVendorPayload, validateVendorDraft } from "../vendorValidation";

interface Props {
  canWrite: boolean;
  canSanction: boolean;
  onOpenProject: (projectId: number) => void;
}

type Panel = { kind: "none" } | { kind: "detail"; id: number } | { kind: "create" } | { kind: "edit"; id: number };

const TYPE_TH = { JURISTIC: "นิติบุคคล", INDIVIDUAL: "บุคคลธรรมดา" } as const;
const SANCTION_TH = { ABANDONED_WORK: "ผู้ทิ้งงาน", SUSPENDED: "ระงับการเสนอราคา" } as const;
const thDate = (iso: string) => new Date(iso).toLocaleDateString("th-TH", { day: "numeric", month: "short", year: "numeric" });

export function VendorsPage({ canWrite, canSanction, onOpenProject }: Props) {
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const [sanctioned, setSanctioned] = useState("");
  const [rows, setRows] = useState<VendorListItem[] | null>(null);
  const [panel, setPanel] = useState<Panel>({ kind: "none" });
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const params = new URLSearchParams();
    if (q.trim()) params.set("q", q.trim());
    if (type) params.set("vendor_type", type);
    if (sanctioned) params.set("sanctioned", sanctioned);
    const t = setTimeout(() => {
      api<VendorListItem[]>(`/api/vendors?${params}`)
        .then((r) => { setRows(r); setError(null); })
        .catch((e: Error) => setError(e.message));
    }, 250);
    return () => clearTimeout(t);
  }, [q, type, sanctioned, reloadKey]);

  const refresh = () => setReloadKey((k) => k + 1);
  const selectedId = panel.kind === "detail" || panel.kind === "edit" ? panel.id : null;

  return (
    <section>
      <div className="page-head">
        <div>
          <h2>ทะเบียนผู้ประกอบการ</h2>
          <p className="muted">{rows ? `${rows.length} ราย` : "กำลังโหลด…"}</p>
        </div>
        {canWrite && <button type="button" onClick={() => setPanel({ kind: "create" })}>+ ลงทะเบียนผู้ประกอบการ</button>}
      </div>

      <div className="filters card vendor-filters">
        <input type="search" placeholder="ค้นหาชื่อหรือเลขประจำตัวผู้เสียภาษี" value={q}
               onChange={(e) => setQ(e.target.value)} aria-label="ค้นหา" />
        <select value={type} onChange={(e) => setType(e.target.value)} aria-label="ประเภท">
          <option value="">ทุกประเภท</option>
          <option value="JURISTIC">นิติบุคคล</option>
          <option value="INDIVIDUAL">บุคคลธรรมดา</option>
        </select>
        <select value={sanctioned} onChange={(e) => setSanctioned(e.target.value)} aria-label="สถานะ">
          <option value="">ทุกสถานะ</option>
          <option value="false">ปกติ</option>
          <option value="true">อยู่ในบัญชีผู้ทิ้งงาน</option>
        </select>
      </div>
      {error && <p role="alert" className="banner-error">{error}</p>}

      <div className={`master-detail ${panel.kind !== "none" ? "has-panel" : ""}`}>
        <ul className="vendor-list">
          {rows?.length === 0 && <li className="card empty">ไม่พบผู้ประกอบการตามเงื่อนไข</li>}
          {rows?.map((v) => (
            <li key={v.vendor_id}>
              <button type="button" className={`vendor-row card ${selectedId === v.vendor_id ? "selected" : ""}`}
                      onClick={() => setPanel({ kind: "detail", id: v.vendor_id })}>
                <span className="vendor-name">
                  {v.name_th}
                  {v.is_sanctioned && <span className="badge badge-cancelled">ผู้ทิ้งงาน</span>}
                </span>
                <span className="meta">{formatTaxId(v.tax_id)} · {TYPE_TH[v.vendor_type]}</span>
                <span className="vendor-stats">
                  <span>เสนอราคา <strong>{v.bids}</strong></span>
                  <span>ได้รับคัดเลือก <strong>{v.wins}</strong></span>
                  <span>มูลค่า <strong>{fullBaht(Number(v.awarded_total))}</strong> บาท</span>
                </span>
              </button>
            </li>
          ))}
        </ul>

        {panel.kind !== "none" && (
          <aside className="detail-panel card">
            <button type="button" className="link back-mobile" onClick={() => setPanel({ kind: "none" })}>← รายการผู้ประกอบการ</button>
            {panel.kind === "detail" && (
              <VendorDetailView key={`${panel.id}-${reloadKey}`} id={panel.id} canWrite={canWrite} canSanction={canSanction}
                                onEdit={() => setPanel({ kind: "edit", id: panel.id })} onChanged={refresh}
                                onOpenProject={onOpenProject} />
            )}
            {(panel.kind === "create" || panel.kind === "edit") && (
              <VendorForm key={panel.kind === "edit" ? panel.id : "new"}
                          editId={panel.kind === "edit" ? panel.id : null}
                          onCancel={() => setPanel(panel.kind === "edit" ? { kind: "detail", id: panel.id } : { kind: "none" })}
                          onSaved={(id) => { refresh(); setPanel({ kind: "detail", id }); }} />
            )}
          </aside>
        )}
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
function VendorDetailView({ id, canWrite, canSanction, onEdit, onChanged, onOpenProject }: {
  id: number; canWrite: boolean; canSanction: boolean; onEdit: () => void; onChanged: () => void;
  onOpenProject: (projectId: number) => void;
}) {
  const [v, setV] = useState<VendorDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showSanction, setShowSanction] = useState(false);

  const load = useCallback(() => {
    api<VendorDetail>(`/api/vendors/${id}`).then(setV).catch((e: Error) => setError(e.message));
  }, [id]);
  useEffect(load, [load]);

  if (error) return <p role="alert" className="banner-error">{error}</p>;
  if (!v) return <p className="muted">กำลังโหลด…</p>;

  const wins = v.projects.filter((p) => p.is_winner);
  const awarded = wins.reduce((s, p) => s + Number(p.agreed_amount ?? p.quoted_amount), 0);

  return (
    <div className="vendor-detail">
      <div className="detail-head">
        <div>
          <h3>{v.name_th}</h3>
          <p className="muted">{TYPE_TH[v.vendor_type]} · ลงทะเบียน {thDate(v.created_at)}</p>
        </div>
        {canWrite && <button type="button" className="ghost" onClick={onEdit}>แก้ไข</button>}
      </div>

      {v.is_sanctioned && (
        <div className="banner-error" role="alert">
          อยู่ในบัญชีรายชื่อผู้ทิ้งงาน — ไม่สามารถรับเป็นผู้ชนะการเสนอราคาได้ (พ.ร.บ. มาตรา 109)
        </div>
      )}

      <div className="mini-stats">
        <div><span>เสนอราคา</span><strong>{v.projects.length}</strong></div>
        <div><span>ได้รับคัดเลือก</span><strong>{wins.length}</strong></div>
        <div><span>มูลค่ารวม (บาท)</span><strong>{fullBaht(awarded)}</strong></div>
      </div>

      <dl className="info-list">
        <dt>เลขประจำตัวผู้เสียภาษี</dt><dd className="num-left">{formatTaxId(v.tax_id)}</dd>
        <dt>ที่อยู่</dt><dd>{v.address_th}</dd>
        <dt>อีเมล</dt><dd>{v.email ?? "—"}</dd>
        <dt>โทรศัพท์</dt><dd>{v.phone_masked ?? "—"}</dd>
        <dt>บัญชีรับเงิน</dt><dd>{v.bank_account_masked ?? "—"}</dd>
      </dl>
      <p className="muted small privacy-note">🔒 เบอร์โทรและเลขบัญชีเก็บแบบเข้ารหัส แสดงเฉพาะ 4 หลักท้าย</p>

      <h4>ประวัติการเข้าร่วมโครงการ</h4>
      {v.projects.length === 0 ? <p className="muted small">ยังไม่เคยเสนอราคา</p> : (
        <ul className="history">
          {v.projects.map((p) => (
            <li key={p.project_id}>
              <button type="button" className="history-row" onClick={() => onOpenProject(p.project_id)}>
                <span>
                  <span className="code">{p.project_code}</span> {p.title_th}
                  <small>{p.method_name_th} · ปีงบประมาณ {p.fiscal_year_be}</small>
                </span>
                <span className="num">
                  {fullBaht(Number(p.agreed_amount ?? p.quoted_amount))}
                  {p.is_winner ? <span className="badge badge-completed">ได้รับคัดเลือก</span>
                               : <span className="badge">เสนอราคา</span>}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="section-head">
        <h4>บัญชีผู้ทิ้งงาน / การระงับ</h4>
        {canSanction && !showSanction && (
          <button type="button" className="ghost danger" onClick={() => setShowSanction(true)}>+ บันทึก</button>
        )}
      </div>
      {v.sanctions.length === 0 && !showSanction && <p className="muted small">ไม่มีประวัติ</p>}
      <ul className="sanctions">
        {v.sanctions.map((s) => (
          <li key={s.sanction_id} className={s.is_active ? "active" : ""}>
            <strong>{SANCTION_TH[s.sanction_type]}</strong> {s.is_active ? "(มีผลอยู่)" : "(สิ้นสุดแล้ว)"}
            <small>หนังสือ {s.reference_no} · {thDate(s.effective_from)} – {s.effective_to ? thDate(s.effective_to) : "ไม่กำหนด"}</small>
          </li>
        ))}
      </ul>
      {showSanction && (
        <SanctionForm vendorId={v.vendor_id} onCancel={() => setShowSanction(false)}
                      onSaved={() => { setShowSanction(false); load(); onChanged(); }} />
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
function SanctionForm({ vendorId, onCancel, onSaved }: { vendorId: number; onCancel: () => void; onSaved: () => void }) {
  const [type, setType] = useState<"ABANDONED_WORK" | "SUSPENDED">("ABANDONED_WORK");
  const [ref, setRef] = useState("");
  const [from, setFrom] = useState(new Date().toISOString().slice(0, 10));
  const [to, setTo] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const problem = ref.trim().length < 3 ? "กรุณากรอกเลขที่หนังสือแจ้งเวียน"
    : to && to < from ? "วันสิ้นสุดต้องไม่ก่อนวันเริ่ม"
    : !confirm ? "กรุณาติ๊กยืนยัน" : null;

  async function save() {
    if (problem) { setError(problem); return; }
    setBusy(true);
    try {
      await api(`/api/vendors/${vendorId}/sanctions`, { method: "POST", body: JSON.stringify({
        sanction_type: type, reference_no: ref.trim(), effective_from: from, effective_to: to || null,
      }) });
      onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? [e.message, ...e.violations.map((v) => v.message)].join(" — ") : "บันทึกไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="sanction-form">
      {error && <p role="alert" className="error">{error}</p>}
      <div className="grid-2">
        <div className="field">
          <label htmlFor="s-type">ประเภท</label>
          <select id="s-type" value={type} onChange={(e) => setType(e.target.value as typeof type)}>
            <option value="ABANDONED_WORK">ผู้ทิ้งงาน</option>
            <option value="SUSPENDED">ระงับการเสนอราคา</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="s-ref">เลขที่หนังสือแจ้งเวียน</label>
          <input id="s-ref" value={ref} onChange={(e) => setRef(e.target.value)} placeholder="กค (กวจ) 0405.2/ว …" />
        </div>
        <div className="field">
          <label htmlFor="s-from">มีผลตั้งแต่</label>
          <input id="s-from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="s-to">ถึง (ถ้ามี)</label>
          <input id="s-to" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        </div>
      </div>
      <label className="ack">
        <input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />
        ยืนยันว่าตรวจสอบกับหนังสือแจ้งเวียนรายชื่อผู้ทิ้งงานแล้ว — ผู้ประกอบการรายนี้จะถูกห้ามรับเป็นผู้ชนะทันที
      </label>
      <div className="form-actions">
        <button type="button" className="ghost" onClick={onCancel}>ยกเลิก</button>
        <button type="button" className="danger-solid" disabled={busy} onClick={save}>{busy ? "กำลังบันทึก…" : "บันทึกผู้ทิ้งงาน"}</button>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
const EMPTY: VendorDraft = { tax_id: "", vendor_type: "JURISTIC", name_th: "", address_th: "", phone: "", email: "", bank_account: "" };

function VendorForm({ editId, onCancel, onSaved }: { editId: number | null; onCancel: () => void; onSaved: (id: number) => void }) {
  const mode = editId ? "edit" : "create";
  const [draft, setDraft] = useState<VendorDraft>(EMPTY);
  const [original, setOriginal] = useState<VendorDraft | undefined>();
  const [masked, setMasked] = useState<{ phone: string | null; bank: string | null }>({ phone: null, bank: null });
  const [typeTouched, setTypeTouched] = useState(false);
  const [touched, setTouched] = useState<Set<string>>(new Set());
  const [showAll, setShowAll] = useState(false);
  const [serverErrors, setServerErrors] = useState<Violation[]>([]);
  const [banner, setBanner] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!editId) return;
    api<VendorDetail>(`/api/vendors/${editId}`).then((v) => {
      const d = { ...EMPTY, tax_id: v.tax_id, vendor_type: v.vendor_type, name_th: v.name_th,
                  address_th: v.address_th, email: v.email ?? "" };
      setDraft(d);
      setOriginal(d);
      setMasked({ phone: v.phone_masked, bank: v.bank_account_masked });
    });
  }, [editId]);

  const errors = useMemo(() => validateVendorDraft(draft, mode), [draft, mode]);
  const set = (k: keyof VendorDraft, v: string) => {
    setDraft((d) => ({ ...d, [k]: v }));
    setServerErrors((s) => s.filter((x) => x.field !== k));
  };
  const errorOf = (k: keyof VendorDraft) =>
    (showAll || touched.has(k) ? errors[k] : undefined) ?? serverErrors.find((x) => x.field === k)?.message;
  const touch = (k: string) => setTouched((t) => new Set(t).add(k));

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setShowAll(true);
    if (Object.keys(errors).length) { setBanner("กรุณาแก้ไขข้อมูลที่ไม่ถูกต้อง"); return; }
    const payload = toVendorPayload(draft, mode, original);
    if (mode === "edit" && Object.keys(payload).length === 0) { onSaved(editId!); return; }
    setBusy(true);
    setBanner(null);
    try {
      const r = mode === "create"
        ? await api<{ vendor_id: number }>("/api/vendors", { method: "POST", body: JSON.stringify(payload) })
        : await api<{ vendor_id: number }>(`/api/vendors/${editId}`, { method: "PATCH", body: JSON.stringify(payload) });
      onSaved(r.vendor_id);
    } catch (err) {
      if (err instanceof ApiError) {
        setServerErrors(err.violations);
        const general = err.violations.filter((v) => !v.field).map((v) => v.message);
        setBanner([err.message, ...general].join(" — "));
      } else setBanner("เชื่อมต่อเซิร์ฟเวอร์ไม่ได้");
    } finally {
      setBusy(false);
    }
  }

  const field = (k: keyof VendorDraft, label: string, input: React.ReactNode, opts: { required?: boolean; help?: string } = {}) => (
    <div className={`field ${errorOf(k) ? "has-error" : ""}`}>
      <label htmlFor={`v-${k}`}>{label}{opts.required && <span aria-hidden> *</span>}</label>
      {input}
      {opts.help && <small className="help">{opts.help}</small>}
      {errorOf(k) && <small role="alert" className="error">{errorOf(k)}</small>}
    </div>
  );
  const taxOk = draft.tax_id.length === 13 && !errors.tax_id;
  // โหมดแก้ไข: ยังไม่แสดงช่องกรอกจนกว่าข้อมูลเดิมจะโหลดเสร็จ (กันสิ่งที่พิมพ์ไว้ถูกค่าเดิมเขียนทับ)
  if (mode === "edit" && !original) return <p className="muted">กำลังโหลดข้อมูล…</p>;

  return (
    <form onSubmit={save} noValidate className="vendor-form">
      <h3>{mode === "create" ? "ลงทะเบียนผู้ประกอบการ" : "แก้ไขข้อมูลผู้ประกอบการ"}</h3>
      {banner && <div role="alert" className="banner-error">{banner}</div>}

      {mode === "create" ? (
        <>
          {field("tax_id", "เลขประจำตัวผู้เสียภาษี (13 หลัก)", (
            <input id="v-tax_id" inputMode="numeric" maxLength={13} value={draft.tax_id} onBlur={() => touch("tax_id")}
                   onChange={(e) => {
                     const v = e.target.value.replace(/\D/g, "");
                     set("tax_id", v);
                     if (!typeTouched && v) setDraft((d) => ({ ...d, tax_id: v, vendor_type: guessVendorType(v) }));
                   }} />
          ), { required: true, help: taxOk ? `✓ ${formatTaxId(draft.tax_id)} — เลขถูกต้อง` : "ระบบตรวจ checksum อัตโนมัติ" })}
          {field("vendor_type", "ประเภทผู้ประกอบการ", (
            <div className="chips" role="radiogroup" id="v-vendor_type">
              {(["JURISTIC", "INDIVIDUAL"] as const).map((t) => (
                <label key={t} className={`chip ${draft.vendor_type === t ? "on" : ""}`}>
                  <input type="radio" name="vendor_type" checked={draft.vendor_type === t}
                         onChange={() => { setTypeTouched(true); set("vendor_type", t); }} />
                  {TYPE_TH[t]}
                </label>
              ))}
            </div>
          ), { required: true })}
        </>
      ) : (
        <dl className="info-list compact"><dt>เลขประจำตัวผู้เสียภาษี</dt><dd>{formatTaxId(draft.tax_id)} ({TYPE_TH[draft.vendor_type]})</dd></dl>
      )}

      {field("name_th", "ชื่อผู้ประกอบการ", (
        <input id="v-name_th" maxLength={500} value={draft.name_th} onBlur={() => touch("name_th")}
               onChange={(e) => set("name_th", e.target.value)} placeholder="บริษัท … จำกัด" />
      ), { required: true })}
      {field("address_th", "ที่อยู่", (
        <textarea id="v-address_th" rows={3} maxLength={5000} value={draft.address_th} onBlur={() => touch("address_th")}
                  onChange={(e) => set("address_th", e.target.value)} />
      ), { required: true })}
      <div className="grid-2">
        {field("phone", "โทรศัพท์", (
          <input id="v-phone" inputMode="tel" maxLength={10} value={draft.phone} onBlur={() => touch("phone")}
                 placeholder={masked.phone ? `เดิม ${masked.phone}` : "0812345678"}
                 onChange={(e) => set("phone", e.target.value.replace(/\D/g, ""))} />
        ), { help: mode === "edit" && masked.phone ? "เว้นว่าง = ไม่เปลี่ยน" : undefined })}
        {field("email", "อีเมล", (
          <input id="v-email" type="email" value={draft.email} onBlur={() => touch("email")}
                 onChange={(e) => set("email", e.target.value)} />
        ))}
      </div>
      {field("bank_account", "เลขบัญชีรับเงิน", (
        <input id="v-bank_account" inputMode="numeric" maxLength={15} value={draft.bank_account}
               onBlur={() => touch("bank_account")} placeholder={masked.bank ? `เดิม ${masked.bank}` : "ตัวเลข 10–15 หลัก"}
               onChange={(e) => set("bank_account", e.target.value.replace(/\D/g, ""))} />
      ), { help: mode === "edit" && masked.bank ? "เว้นว่าง = ไม่เปลี่ยน · ข้อมูลถูกเข้ารหัส" : "ข้อมูลถูกเข้ารหัสก่อนบันทึก" })}

      <div className="form-actions">
        <button type="button" className="ghost" onClick={onCancel}>ยกเลิก</button>
        <button type="submit" disabled={busy}>{busy ? "กำลังบันทึก…" : "บันทึก"}</button>
      </div>
    </form>
  );
}
