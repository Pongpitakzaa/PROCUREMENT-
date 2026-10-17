/**
 * ไฟล์แนบ PDF ของขั้นตอน: อัปโหลด / รายการ / เปิดดูในหน้าเว็บ (iframe จาก blob ที่ดึงมาพร้อม token) / ดาวน์โหลด / ลบ
 * - เซิร์ฟเวอร์ตรวจว่าเป็น PDF จริง ไม่เกิน 10 MB และไม่มีสคริปต์ฝัง · ฝั่งนี้ตรวจเบื้องต้นเพื่อ UX
 * - ไม่ใช้ <iframe src="/api/..."> ตรง ๆ เพราะ token อยู่ในหน่วยความจำ (ไม่ใช่ cookie) → ดึงเป็น blob ก่อน
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "../api";
import type { StepAttachment } from "../types";

const MAX_BYTES = 10 * 1024 * 1024;

function fmtSize(n: number): string {
  return n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`;
}

export function StepAttachments({ projectId, stepCode, canUpload, canApprove, myUserId }: {
  projectId: number; stepCode: string; canUpload: boolean; canApprove: boolean; myUserId: number | null;
}) {
  const [rows, setRows] = useState<StepAttachment[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [viewing, setViewing] = useState<{ a: StepAttachment; url: string } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const base = `/api/projects/${projectId}/steps/${stepCode}/attachments`;

  const load = useCallback(() => {
    api<StepAttachment[]>(base).then((r) => { setRows(r); setError(null); }).catch((e) => setError(errText(e)));
  }, [base]);
  useEffect(load, [load]);
  useEffect(() => () => { if (viewing) URL.revokeObjectURL(viewing.url); }, [viewing]);

  async function upload(file: File) {
    if (file.size > MAX_BYTES) { setError("ไฟล์ใหญ่เกิน 10 MB"); return; }
    if (!/\.pdf$/i.test(file.name) && file.type !== "application/pdf") { setError("รับเฉพาะไฟล์ PDF"); return; }
    const fd = new FormData();
    fd.set("file", file);
    setBusy(true); setError(null);
    try {
      await api(base, { method: "POST", body: fd });
      load();
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function view(a: StepAttachment) {
    setBusy(true); setError(null);
    try {
      const blob = await api<Blob>(`/api/attachments/${a.attachment_id}`);
      const url = URL.createObjectURL(blob.type === "application/pdf" ? blob : new Blob([blob], { type: "application/pdf" }));
      setViewing({ a, url });
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  }

  async function download(a: StepAttachment) {
    try {
      const blob = await api<Blob>(`/api/attachments/${a.attachment_id}?download=true`);
      const url = URL.createObjectURL(blob);
      const link = Object.assign(document.createElement("a"), { href: url, download: a.file_name });
      document.body.append(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e) {
      setError(errText(e));
    }
  }

  async function remove(a: StepAttachment) {
    if (!confirm(`ลบไฟล์ "${a.file_name}" ?`)) return;
    setBusy(true);
    try {
      await api(`/api/attachments/${a.attachment_id}`, { method: "DELETE" });
      load();
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="attachments" aria-label="ไฟล์แนบ PDF">
      <div className="section-head">
        <h4>📎 ไฟล์แนบ (PDF) {rows && rows.length > 0 && <small className="muted">{rows.length} ไฟล์</small>}</h4>
        {canUpload && (
          <label className={`ghost upload-btn ${busy ? "disabled" : ""}`}>
            {busy ? "กำลังทำงาน…" : "+ แนบ PDF"}
            <input ref={fileRef} type="file" accept="application/pdf,.pdf" hidden disabled={busy}
                   onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); }} />
          </label>
        )}
      </div>
      {error && <p role="alert" className="banner-error">{error}</p>}
      {rows === null ? <p className="muted small">กำลังโหลด…</p>
        : rows.length === 0 ? <p className="muted small">ยังไม่มีไฟล์แนบ{canUpload ? " — แนบเอกสารประกอบ เช่น ใบเสนอราคา หนังสืออนุมัติ ที่สแกนเป็น PDF" : ""}</p>
        : (
          <ul className="attach-list">
            {rows.map((a) => (
              <li key={a.attachment_id}>
                <button type="button" className="link name" onClick={() => void view(a)} title="เปิดดู">{a.file_name}</button>
                <span className="muted small">{fmtSize(a.size_bytes)} · {a.uploaded_by} · {new Date(a.uploaded_at).toLocaleDateString("th-TH", { dateStyle: "medium" })}</span>
                <span className="actions">
                  <button type="button" className="link" onClick={() => void view(a)}>ดู</button>
                  <button type="button" className="link" onClick={() => void download(a)}>ดาวน์โหลด</button>
                  {(canApprove || a.uploaded_by_id === myUserId) && <button type="button" className="link danger" onClick={() => void remove(a)}>ลบ</button>}
                </span>
              </li>
            ))}
          </ul>
        )}
      {viewing && (
        <div className="pdf-viewer" role="dialog" aria-label={viewing.a.file_name}>
          <div className="pdf-head">
            <strong>{viewing.a.file_name}</strong>
            <span>
              <a className="link" href={viewing.url} target="_blank" rel="noopener noreferrer">เปิดแท็บใหม่</a>
              <button type="button" className="ghost" onClick={() => setViewing(null)}>ปิด</button>
            </span>
          </div>
          <iframe src={viewing.url} title={viewing.a.file_name} />
        </div>
      )}
    </section>
  );
}

function errText(e: unknown): string {
  return e instanceof ApiError ? e.message : "ดำเนินการไม่สำเร็จ";
}
