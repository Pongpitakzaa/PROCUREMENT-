/**
 * หน้าผู้ดูแลระบบ — แท็บแสดงตามสิทธิ์ของผู้ใช้
 * - สำรอง/กู้คืนข้อมูล (backup:run / restore:run)
 * - แบบฟอร์มกรมบัญชีกลาง (template:manage = อัปโหลด, template:verify = ตรวจรับรอง; ต้องคนละคน)
 * - Audit Log + ตรวจ hash chain (audit:read)
 * - กลุ่ม LINE สำหรับแจ้งเตือน (user:manage)
 */
import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "../api";
import type { AuditRow, BackupManifest, LineChannel, TemplateRow } from "../types";

interface Props {
  permissions: string[];
  userId: number;
}

type TabKey = "backup" | "templates" | "audit" | "line";

const thDateTime = (iso: string) =>
  new Date(iso).toLocaleString("th-TH", { day: "numeric", month: "short", year: "2-digit", hour: "2-digit", minute: "2-digit" });
const thDate = (iso: string) => new Date(iso).toLocaleDateString("th-TH", { day: "numeric", month: "short", year: "numeric" });
const fileSize = (b: number) => (b >= 1 << 20 ? `${(b / (1 << 20)).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`);
const errText = (e: unknown) =>
  e instanceof ApiError ? [e.message, ...e.violations.map((v) => v.message)].join(" — ") : "เชื่อมต่อเซิร์ฟเวอร์ไม่ได้";

export function AdminPage({ permissions, userId }: Props) {
  const can = (p: string) => permissions.includes(p);
  const tabs: { key: TabKey; label: string; show: boolean }[] = [
    { key: "backup", label: "สำรอง/กู้คืนข้อมูล", show: can("backup:run") },
    { key: "templates", label: "แบบฟอร์มกรมบัญชีกลาง", show: can("template:manage") || can("template:verify") },
    { key: "audit", label: "Audit Log", show: can("audit:read") },
    { key: "line", label: "กลุ่ม LINE", show: can("user:manage") },
  ];
  const visible = tabs.filter((t) => t.show);
  const [tab, setTab] = useState<TabKey | undefined>(visible[0]?.key);

  if (!tab) return <div className="card empty">ไม่มีสิทธิ์เข้าถึงส่วนผู้ดูแลระบบ</div>;

  return (
    <section>
      <div className="page-head">
        <div>
          <h2>ผู้ดูแลระบบ</h2>
          <p className="muted">ทุกการดำเนินการในหน้านี้ถูกบันทึกใน Audit Log</p>
        </div>
      </div>
      <div className="tabs" role="tablist">
        {visible.map((t) => (
          <button key={t.key} type="button" role="tab" aria-selected={tab === t.key}
                  className={tab === t.key ? "on" : ""} onClick={() => setTab(t.key)}>{t.label}</button>
        ))}
      </div>
      {tab === "backup" && <BackupTab canRestore={can("restore:run")} />}
      {tab === "templates" && <TemplatesTab canManage={can("template:manage")} canVerify={can("template:verify")} userId={userId} />}
      {tab === "audit" && <AuditTab />}
      {tab === "line" && <LineTab />}
    </section>
  );
}

/* ================================================================== */
function BackupTab({ canRestore }: { canRestore: boolean }) {
  const [rows, setRows] = useState<BackupManifest[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [restoring, setRestoring] = useState<BackupManifest | null>(null);

  const load = useCallback(() => { api<BackupManifest[]>("/api/admin/backups").then(setRows).catch((e) => setMsg({ ok: false, text: errText(e) })); }, []);
  useEffect(load, [load]);

  async function backupNow() {
    setBusy(true);
    setMsg(null);
    try {
      const m = await api<BackupManifest>("/api/admin/backups", { method: "POST" });
      setMsg({ ok: true, text: `สำรองข้อมูลสำเร็จ: ${m.file_name} (${fileSize(m.size_bytes)})` });
      load();
    } catch (e) {
      setMsg({ ok: false, text: errText(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="admin-grid">
      <div className="card panel-lg">
        <div className="section-head">
          <div>
            <h3>ไฟล์สำรองข้อมูล</h3>
            <p className="muted small">pg_dump เข้ารหัส AES-256-GCM · ตรวจ SHA-256 ก่อนกู้คืนทุกครั้ง</p>
          </div>
          <button type="button" onClick={backupNow} disabled={busy}>{busy ? "กำลังสำรอง…" : "สำรองข้อมูลตอนนี้"}</button>
        </div>
        {msg && <p role="status" className={msg.ok ? "banner-ok" : "banner-error"}>{msg.text}</p>}
        {rows?.length === 0 && <div className="empty">ยังไม่มีไฟล์สำรองข้อมูล</div>}
        {rows && rows.length > 0 && (
          <div className="table-wrap">
            <table className="data-table backup-table">
              <thead><tr><th>ไฟล์</th><th>วันที่</th><th>ขนาด</th><th className="hide-sm">ผู้สั่ง</th><th className="hide-sm">SHA-256</th>{canRestore && <th />}</tr></thead>
              <tbody>
                {rows.map((b) => (
                  <tr key={b.file_name}>
                    <th scope="row">
                      {b.file_name}
                      {b.file_name.includes("pre-restore") && <span className="badge">สำรองก่อนกู้คืน</span>}
                    </th>
                    <td>{thDateTime(b.created_at)}</td>
                    <td>{fileSize(b.size_bytes)}</td>
                    <td className="hide-sm">{b.requested_by}</td>
                    <td className="hide-sm"><code title={b.sha256}>{b.sha256.slice(0, 12)}…</code></td>
                    {canRestore && (
                      <td><button type="button" className="ghost danger" onClick={() => setRestoring(b)}>กู้คืน</button></td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <aside className="card panel-lg">
        {restoring ? (
          <RestoreForm backup={restoring} onCancel={() => setRestoring(null)}
                       onDone={(text) => { setRestoring(null); setMsg({ ok: true, text }); load(); }} />
        ) : (
          <>
            <h3>ข้อแนะนำ</h3>
            <ul className="tips">
              <li>สำรองข้อมูลก่อนปรับปรุงระบบหรือนำเข้าข้อมูลจำนวนมาก</li>
              <li>คัดลอกไฟล์สำรองออกนอกเครื่องแม่ข่ายเป็นประจำ (หลัก 3-2-1)</li>
              <li>การกู้คืนจะ<strong>แทนที่ข้อมูลทั้งหมด</strong> ด้วยข้อมูล ณ เวลาที่สำรอง — ระบบสำรองสถานะปัจจุบันให้อัตโนมัติก่อนเสมอ</li>
              <li>ควรแจ้งผู้ใช้งานและหยุดการบันทึกข้อมูลระหว่างกู้คืน</li>
            </ul>
          </>
        )}
      </aside>
    </div>
  );
}

const CONFIRM_TEXT = "ยืนยันกู้คืนข้อมูล";

function RestoreForm({ backup, onCancel, onDone }: { backup: BackupManifest; onCancel: () => void; onDone: (msg: string) => void }) {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ready = password.length > 0 && confirm === CONFIRM_TEXT;

  async function run() {
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ restored: string; safety_backup: string; audit_rows_carried_over: number }>("/api/admin/restore", {
        method: "POST", body: JSON.stringify({ file_name: backup.file_name, password, confirm_text: confirm }),
      });
      onDone(`กู้คืนข้อมูลจาก ${r.restored} สำเร็จ · สำรองสถานะก่อนกู้คืนไว้ที่ ${r.safety_backup}`
             + ` · ยก Audit Log ที่เกิดหลังเวลาสำรอง ${r.audit_rows_carried_over} รายการมาต่อท้ายแล้ว`);
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="restore-form">
      <h3>กู้คืนข้อมูล</h3>
      <div className="banner-error" role="alert">
        ข้อมูลทั้งหมดจะถูกแทนที่ด้วยข้อมูล ณ <strong>{thDateTime(backup.created_at)}</strong> — ข้อมูลที่บันทึกหลังจากนั้นจะหายไป
        (ระบบจะสำรองสถานะปัจจุบันไว้ให้ก่อน และ Audit Log จะไม่หายไป)
      </div>
      <dl className="info-list compact"><dt>ไฟล์</dt><dd>{backup.file_name}</dd></dl>
      <div className="field">
        <label htmlFor="r-password">ยืนยันรหัสผ่านของคุณ</label>
        <input id="r-password" type="password" autoComplete="current-password" value={password}
               onChange={(e) => setPassword(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="r-confirm">พิมพ์ “{CONFIRM_TEXT}” เพื่อยืนยัน</label>
        <input id="r-confirm" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="off" />
      </div>
      {error && <p role="alert" className="error">{error}</p>}
      <div className="form-actions">
        <button type="button" className="ghost" onClick={onCancel} disabled={busy}>ยกเลิก</button>
        <button type="button" className="danger-solid" disabled={!ready || busy} onClick={run}>
          {busy ? "กำลังกู้คืน…" : "กู้คืนข้อมูล"}
        </button>
      </div>
    </div>
  );
}

/* ================================================================== */
const CGD_URL = /^https:\/\/([a-z0-9-]+\.)*gprocurement\.go\.th\/\S+$/i;
const TEMPLATE_STATUS = { ACTIVE: ["ใช้งานอยู่", "badge-completed"], PENDING: ["รอตรวจรับรอง", "badge-awarded"], RETIRED: ["เลิกใช้", ""] } as const;

function TemplatesTab({ canManage, canVerify, userId }: { canManage: boolean; canVerify: boolean; userId: number }) {
  const [rows, setRows] = useState<TemplateRow[] | null>(null);
  const [types, setTypes] = useState<{ code: string; name_th: string }[]>([]);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [open, setOpen] = useState<number | null>(null);

  const load = useCallback(() => { api<TemplateRow[]>("/api/admin/templates").then(setRows).catch((e) => setMsg({ ok: false, text: errText(e) })); }, []);
  useEffect(() => {
    load();
    api<{ code: string; name_th: string }[]>("/api/admin/document-types").then(setTypes);
  }, [load]);

  async function verify(t: TemplateRow) {
    try {
      await api(`/api/admin/templates/${t.template_id}/verify`, { method: "POST" });
      setMsg({ ok: true, text: `เปิดใช้แบบฟอร์ม “${t.document_type_name_th}” รุ่น ${t.version_label} แล้ว (ฉบับเดิมถูกปิดอัตโนมัติ)` });
      load();
    } catch (e) {
      setMsg({ ok: false, text: errText(e) });
    }
  }

  const missing = types.filter((d) => !rows?.some((r) => r.document_type_code === d.code && r.is_active));

  return (
    <div className="admin-grid">
      <div className="card panel-lg">
        <h3>ทะเบียนแบบฟอร์ม</h3>
        <p className="muted small">ใช้เฉพาะแบบฟอร์มจาก gprocurement.go.th · ผู้อัปโหลดและผู้ตรวจรับรองต้องเป็นคนละคน · ตรวจ SHA-256 ของไฟล์ทุกครั้งที่ใช้</p>
        {msg && <p role="status" className={msg.ok ? "banner-ok" : "banner-error"}>{msg.text}</p>}
        {rows?.length === 0 && <div className="empty">ยังไม่มีแบบฟอร์มในระบบ</div>}
        <ul className="template-list">
          {rows?.map((t) => {
            const [label, cls] = TEMPLATE_STATUS[t.status];
            const canVerifyThis = canVerify && t.status === "PENDING" && t.uploaded_by_id !== userId;
            return (
              <li key={t.template_id} className={`template-row ${t.status.toLowerCase()}`}>
                <div className="template-main">
                  <strong>{t.document_type_name_th}</strong>
                  <span className="muted small">รุ่น {t.version_label} · {t.file_format} · มีผล {thDate(t.effective_from)} · {t.cgd_reference}</span>
                  <span className="muted small">
                    อัปโหลด: {t.uploaded_by ?? "—"}{t.verified_by && ` · รับรอง: ${t.verified_by}`} ·{" "}
                    <a href={t.source_url} target="_blank" rel="noopener noreferrer">แหล่งที่มา</a> ·{" "}
                    <button type="button" className="link inline" onClick={() => setOpen(open === t.template_id ? null : t.template_id)}>
                      ตัวแปร {t.variables.length} รายการ
                    </button>
                  </span>
                  {open === t.template_id && <code className="vars">{t.variables.join(", ") || "—"}</code>}
                </div>
                <div className="template-side">
                  <span className={`badge ${cls}`}>{label}</span>
                  {!t.file_ok && <span className="badge badge-cancelled" title="ไฟล์บน storage ไม่ตรงกับ SHA-256 ที่รับรองไว้">ไฟล์ถูกแก้ไข!</span>}
                  {canVerifyThis && <button type="button" onClick={() => verify(t)}>ตรวจรับรองและเปิดใช้</button>}
                  {canVerify && t.status === "PENDING" && t.uploaded_by_id === userId && (
                    <span className="muted small">รอผู้อื่นตรวจรับรอง</span>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
        {missing.length > 0 && (
          <p className="muted small">ยังไม่มีแบบฟอร์มที่ใช้งานได้สำหรับ: {missing.map((m) => m.name_th).join(", ")}</p>
        )}
      </div>

      {canManage && (
        <aside className="card panel-lg">
          <TemplateUpload types={types} onUploaded={(text) => { setMsg({ ok: true, text }); load(); }} />
        </aside>
      )}
    </div>
  );
}

function TemplateUpload({ types, onUploaded }: { types: { code: string; name_th: string }[]; onUploaded: (msg: string) => void }) {
  const [docType, setDocType] = useState("");
  const [version, setVersion] = useState("");
  const [url, setUrl] = useState("");
  const [ref, setRef] = useState("");
  const [from, setFrom] = useState(new Date().toISOString().slice(0, 10));
  const [file, setFile] = useState<File | null>(null);
  const [schema, setSchema] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const isXlsx = file?.name.toLowerCase().endsWith(".xlsx") ?? false;

  const problems = [
    !docType && "เลือกประเภทเอกสาร",
    !version.trim() && "กรอกรุ่น/ฉบับ",
    url && !CGD_URL.test(url) ? "แหล่งที่มาต้องเป็น https://…gprocurement.go.th/…" : !url && "กรอกแหล่งที่มา",
    ref.trim().length < 3 && "กรอกเลขหนังสือเวียน/ประกาศ",
    !file && "เลือกไฟล์ .docx หรือ .xlsx",
    file && file.size > 10 * 1024 * 1024 && "ไฟล์ใหญ่เกิน 10 MB",
    isXlsx && !schema.trim() && "แบบฟอร์ม Excel ต้องระบุตำแหน่งเซลล์ (JSON)",
  ].filter(Boolean) as string[];

  async function upload(e: React.FormEvent) {
    e.preventDefault();
    if (problems.length) { setError(problems.join(" · ")); return; }
    const fd = new FormData();
    fd.set("document_type_code", docType);
    fd.set("version_label", version.trim());
    fd.set("source_url", url.trim());
    fd.set("cgd_reference", ref.trim());
    fd.set("effective_from", from);
    fd.set("file", file!);
    if (isXlsx) fd.set("xlsx_variable_schema", schema);
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ template_id: number; variables: { variables?: string[] } }>("/api/admin/templates", { method: "POST", body: fd });
      onUploaded(`อัปโหลดแล้ว (พบตัวแปร ${r.variables.variables?.length ?? 0} รายการ) — รอหัวหน้าเจ้าหน้าที่ตรวจรับรองก่อนใช้งาน`);
      setVersion(""); setRef(""); setFile(null); setSchema("");
      (e.target as HTMLFormElement).reset();
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={upload} noValidate>
      <h3>อัปโหลดแบบฟอร์ม</h3>
      <p className="muted small">ดาวน์โหลดแบบฟอร์มจากเว็บไซต์กรมบัญชีกลาง แทนช่องว่างด้วยตัวแปร เช่น <code>{"{{ project_title }}"}</code> แล้วอัปโหลดที่นี่</p>
      <div className="field">
        <label htmlFor="t-type">ประเภทเอกสาร</label>
        <select id="t-type" value={docType} onChange={(e) => setDocType(e.target.value)}>
          <option value="">— เลือก —</option>
          {types.map((t) => <option key={t.code} value={t.code}>{t.name_th}</option>)}
        </select>
      </div>
      <div className="grid-2">
        <div className="field">
          <label htmlFor="t-ver">รุ่น/ฉบับ</label>
          <input id="t-ver" maxLength={30} value={version} onChange={(e) => setVersion(e.target.value)} placeholder="2570.1" />
        </div>
        <div className="field">
          <label htmlFor="t-from">มีผลตั้งแต่</label>
          <input id="t-from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </div>
      </div>
      <div className={`field ${url && !CGD_URL.test(url) ? "has-error" : ""}`}>
        <label htmlFor="t-url">แหล่งที่มา (URL กรมบัญชีกลาง)</label>
        <input id="t-url" type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://www.gprocurement.go.th/…" />
        {url && !CGD_URL.test(url) && <small className="error">ต้องเป็นเว็บไซต์ gprocurement.go.th เท่านั้น</small>}
      </div>
      <div className="field">
        <label htmlFor="t-ref">เลขหนังสือเวียน/ประกาศ กวพ.</label>
        <input id="t-ref" maxLength={255} value={ref} onChange={(e) => setRef(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="t-file">ไฟล์ (.docx / .xlsx, ไม่เกิน 10 MB, ห้ามมี macro)</label>
        <input id="t-file" type="file" accept=".docx,.xlsx" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </div>
      {isXlsx && (
        <div className="field">
          <label htmlFor="t-schema">ตำแหน่งเซลล์ (JSON)</label>
          <textarea id="t-schema" rows={4} value={schema} onChange={(e) => setSchema(e.target.value)}
                    placeholder='{"cells": {"C3": "project_title"}}' />
        </div>
      )}
      {error && <p role="alert" className="error">{error}</p>}
      <button type="submit" className="full" disabled={busy}>{busy ? "กำลังอัปโหลด…" : "อัปโหลด"}</button>
    </form>
  );
}

/* ================================================================== */
const ACTION_TH: Record<string, string> = {
  LOGIN: "เข้าสู่ระบบ", LOGIN_FAILED: "เข้าสู่ระบบไม่สำเร็จ", LOGIN_LOCKED: "บัญชีถูกล็อก",
  CREATE: "สร้างข้อมูล", UPDATE: "แก้ไขข้อมูล", STEP_SUBMIT: "ส่งพิจารณา", STEP_APPROVE: "อนุมัติ",
  STEP_REJECT: "ส่งกลับแก้ไข", EXPORT: "สร้างเอกสาร", DOWNLOAD: "ดาวน์โหลดเอกสาร", EXPORT_REPORT: "ส่งออกรายงาน",
  LINE_SEND: "ส่ง LINE", SANCTION: "บันทึกผู้ทิ้งงาน", TEMPLATE_UPLOAD: "อัปโหลดแบบฟอร์ม",
  TEMPLATE_VERIFY: "รับรองแบบฟอร์ม", BACKUP: "สำรองข้อมูล", RESTORE_REQUESTED: "ขอกู้คืนข้อมูล", RESTORE: "กู้คืนข้อมูล",
};
const SENSITIVE = new Set(["LOGIN_FAILED", "LOGIN_LOCKED", "RESTORE_REQUESTED", "RESTORE", "SANCTION", "TEMPLATE_VERIFY"]);

function AuditTab() {
  const [action, setAction] = useState("");
  const [username, setUsername] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [chain, setChain] = useState<{ intact: boolean; first_broken_audit_id: number | null } | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);

  const query = useCallback(async (before: number | null) => {
    const p = new URLSearchParams({ limit: "30" });
    if (action) p.set("action", action);
    if (username.trim()) p.set("username", username.trim());
    if (from) p.set("date_from", from);
    if (to) p.set("date_to", to);
    if (before) p.set("before_id", String(before));
    setLoading(true);
    try {
      const r = await api<{ items: AuditRow[]; next_before_id: number | null }>(`/api/admin/audit?${p}`);
      setRows((prev) => (before ? [...prev, ...r.items] : r.items));
      setNext(r.next_before_id);
      setError(null);
    } catch (e) {
      setError(errText(e));
    } finally {
      setLoading(false);
    }
  }, [action, username, from, to]);

  useEffect(() => {
    const t = setTimeout(() => query(null), 300);
    return () => clearTimeout(t);
  }, [query]);

  return (
    <div className="card panel-lg">
      <div className="section-head">
        <div>
          <h3>Audit Log</h3>
          <p className="muted small">บันทึกแบบ append-only เชื่อมกันด้วย hash chain — แก้หรือลบแถวใดจะตรวจพบได้</p>
        </div>
        <button type="button" className="ghost" onClick={() => api<typeof chain>("/api/admin/audit/verify").then(setChain).catch((e) => setError(errText(e)))}>
          ตรวจความถูกต้องของ Audit Chain
        </button>
      </div>
      {chain && (
        <p role="status" className={chain.intact ? "banner-ok" : "banner-error"}>
          {chain.intact ? "✓ Audit chain สมบูรณ์ ไม่พบการแก้ไขย้อนหลัง"
                        : `✗ พบความผิดปกติตั้งแต่รายการ #${chain.first_broken_audit_id} — แจ้งผู้ตรวจสอบภายในทันที`}
        </p>
      )}
      <div className="filters audit-filters">
        <select value={action} onChange={(e) => setAction(e.target.value)} aria-label="การกระทำ">
          <option value="">ทุกการกระทำ</option>
          {Object.entries(ACTION_TH).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="ชื่อผู้ใช้ (ตรงตัว)" aria-label="ชื่อผู้ใช้" />
        <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} aria-label="ตั้งแต่วันที่" />
        <input type="date" value={to} onChange={(e) => setTo(e.target.value)} aria-label="ถึงวันที่" />
      </div>
      {error && <p role="alert" className="banner-error">{error}</p>}
      <div className="table-wrap">
        <table className="data-table audit-table">
          <thead><tr><th>#</th><th>เวลา</th><th>ผู้ใช้</th><th>การกระทำ</th><th>รายการ</th><th>IP</th><th /></tr></thead>
          <tbody>
            {rows.map((r) => (
              <AuditRowView key={r.audit_id} r={r} open={expanded === r.audit_id}
                            onToggle={() => setExpanded(expanded === r.audit_id ? null : r.audit_id)} />
            ))}
          </tbody>
        </table>
      </div>
      {!loading && rows.length === 0 && <div className="empty">ไม่พบรายการตามเงื่อนไข</div>}
      {next && <button type="button" className="ghost full" disabled={loading} onClick={() => query(next)}>{loading ? "กำลังโหลด…" : "โหลดเพิ่ม"}</button>}
    </div>
  );
}

function AuditRowView({ r, open, onToggle }: { r: AuditRow; open: boolean; onToggle: () => void }) {
  const hasDetail = r.old_values || r.new_values;
  return (
    <>
      <tr className={SENSITIVE.has(r.action) ? "sensitive" : ""}>
        <td className="muted">{r.audit_id}</td>
        <td>{thDateTime(r.occurred_at)}</td>
        <td>{r.username ?? <span className="muted">—</span>}</td>
        <td><span className="action">{ACTION_TH[r.action] ?? r.action}</span></td>
        <td>{r.entity_table ? `${r.entity_table}${r.entity_id ? ` #${r.entity_id}` : ""}` : "—"}</td>
        <td className="muted">{r.ip_address ?? "—"}</td>
        <td>{hasDetail && <button type="button" className="link inline" onClick={onToggle}>{open ? "ซ่อน" : "รายละเอียด"}</button>}</td>
      </tr>
      {open && (
        <tr className="detail-row">
          <td colSpan={7}>
            {r.old_values && <div><strong>ก่อน</strong><pre>{JSON.stringify(r.old_values, null, 2)}</pre></div>}
            {r.new_values && <div><strong>หลัง</strong><pre>{JSON.stringify(r.new_values, null, 2)}</pre></div>}
            <small className="muted">row hash: <code>{r.row_hash}</code></small>
          </td>
        </tr>
      )}
    </>
  );
}

/* ================================================================== */
const LINE_ID = /^[CU][0-9a-f]{32}$/;

function LineTab() {
  const [rows, setRows] = useState<LineChannel[] | null>(null);
  const [name, setName] = useState("");
  const [lineTo, setLineTo] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => { api<LineChannel[]>("/api/admin/line-channels").then(setRows).catch((e) => setMsg({ ok: false, text: errText(e) })); }, []);
  useEffect(load, [load]);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !LINE_ID.test(lineTo)) { setMsg({ ok: false, text: "กรอกชื่อกลุ่ม และ ID ให้ถูกรูปแบบ" }); return; }
    setBusy(true);
    try {
      await api("/api/admin/line-channels", { method: "POST", body: JSON.stringify({ name_th: name.trim(), line_to: lineTo }) });
      setMsg({ ok: true, text: `เพิ่มกลุ่ม “${name.trim()}” แล้ว` });
      setName(""); setLineTo("");
      load();
    } catch (err) {
      setMsg({ ok: false, text: errText(err) });
    } finally {
      setBusy(false);
    }
  }

  async function toggle(ch: LineChannel) {
    try {
      await api(`/api/admin/line-channels/${ch.channel_id}`, { method: "PATCH", body: JSON.stringify({ is_active: !ch.is_active }) });
      load();
    } catch (e) {
      setMsg({ ok: false, text: errText(e) });
    }
  }

  return (
    <div className="admin-grid">
      <div className="card panel-lg">
        <h3>กลุ่ม LINE ที่รับการแจ้งเตือน</h3>
        <p className="muted small">ส่งผ่าน LINE Messaging API · ID ของกลุ่มเก็บแบบเข้ารหัส แสดงเฉพาะ 4 ตัวท้าย</p>
        {msg && <p role="status" className={msg.ok ? "banner-ok" : "banner-error"}>{msg.text}</p>}
        {rows?.length === 0 && <div className="empty">ยังไม่มีกลุ่ม LINE</div>}
        <ul className="channel-list">
          {rows?.map((ch) => (
            <li key={ch.channel_id}>
              <div>
                <strong>{ch.name_th}</strong>
                <span className="muted small">{ch.line_to_masked} · ส่งล่าสุด {ch.last_sent_at ? thDateTime(ch.last_sent_at) : "—"}</span>
              </div>
              <label className="switch">
                <input type="checkbox" checked={ch.is_active} onChange={() => toggle(ch)} />
                <span>{ch.is_active ? "เปิดใช้" : "ปิด"}</span>
              </label>
            </li>
          ))}
        </ul>
      </div>
      <aside className="card panel-lg">
        <form onSubmit={add} noValidate>
          <h3>เพิ่มกลุ่ม LINE</h3>
          <ol className="tips">
            <li>สร้าง LINE Official Account และเปิด Messaging API</li>
            <li>เชิญบัญชีเข้ากลุ่มงานพัสดุ</li>
            <li>นำ groupId จาก webhook event “join” มากรอกด้านล่าง</li>
          </ol>
          <div className="field">
            <label htmlFor="l-name">ชื่อกลุ่ม</label>
            <input id="l-name" maxLength={100} value={name} onChange={(e) => setName(e.target.value)} placeholder="กลุ่มงานพัสดุ" />
          </div>
          <div className={`field ${lineTo && !LINE_ID.test(lineTo) ? "has-error" : ""}`}>
            <label htmlFor="l-to">groupId / userId</label>
            <input id="l-to" value={lineTo} onChange={(e) => setLineTo(e.target.value.trim())} placeholder="C + ตัวอักษร 32 ตัว" />
            {lineTo && !LINE_ID.test(lineTo) && <small className="error">ต้องขึ้นต้นด้วย C หรือ U ตามด้วย 0-9/a-f 32 ตัว</small>}
          </div>
          <button type="submit" className="full" disabled={busy}>{busy ? "กำลังบันทึก…" : "เพิ่มกลุ่ม"}</button>
        </form>
      </aside>
    </div>
  );
}
