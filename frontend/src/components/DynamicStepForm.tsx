/**
 * Dynamic Form: สร้างฟอร์มจาก FieldSpec ที่ backend ส่งมา (ไม่ hard-code ฟอร์มรายขั้นตอนใน UI)
 * → เพิ่ม/แก้ช่องข้อมูลตามแบบฟอร์มกรมบัญชีกลางที่ backend ที่เดียว หน้าจอเปลี่ยนตามอัตโนมัติ
 *
 * Validation 2 จังหวะ: (1) ตรวจทันทีฝั่ง client เพื่อ UX  (2) แสดงผลตรวจของ server (แหล่งความจริง)
 * React escape ข้อความทุกจุดอัตโนมัติ — ห้ามใช้ dangerouslySetInnerHTML กับข้อมูลจากผู้ใช้/เซิร์ฟเวอร์
 */
import { useEffect, useMemo, useState } from "react";
import { ApiError, api } from "../api";
import type { FieldSpec, FormValues, StepFormResponse, Violation } from "../types";
import { isVisible, toPayload, validateForm } from "../validation";

interface Props {
  projectId: number;
  stepCode: string;
  canApprove: boolean;
  /** ยกเลิกขั้นตอน (ย้อนกลับ): ผู้ส่งเองหรือผู้มีสิทธิ์อนุมัติ — server ตรวจสิทธิ์จริงอีกครั้ง */
  canRevert: boolean;
  onSubmitted: () => void;
}

/** ยกเลิกขั้นตอนที่ส่ง/อนุมัติแล้ว เพื่อย้อนกลับมาแก้ไข — ต้องระบุเหตุผล (ลง audit + แจ้ง LINE) */
function RevertPanel({ projectId, stepCode, status, onDone }: { projectId: number; stepCode: string; status: string; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function revert() {
    if (reason.trim().length < 3) { setError("กรุณาระบุเหตุผล (อย่างน้อย 3 ตัวอักษร)"); return; }
    setBusy(true); setError(null);
    try {
      await api(`/api/projects/${projectId}/steps/${stepCode}/revert`, { method: "POST", body: JSON.stringify({ reason: reason.trim() }) });
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? [err.message, ...err.violations.map((v) => v.message)].join(" — ") : "ยกเลิกไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <p className="revert-hint">
        <button type="button" className="link" onClick={() => setOpen(true)}>↩ ยกเลิกขั้นตอนนี้เพื่อย้อนกลับไปแก้ไข</button>
        <small className="muted"> ({status === "APPROVED" ? "อนุมัติแล้ว — เฉพาะผู้มีสิทธิ์อนุมัติ" : "ส่งพิจารณาแล้ว — ผู้ส่งเองหรือผู้มีสิทธิ์อนุมัติ"})</small>
      </p>
    );
  }
  return (
    <div className="decision revert">
      <h4>ยกเลิกขั้นตอน (ย้อนกลับไปแก้ไข)</h4>
      <p className="muted small">ข้อมูลที่กรอกไว้จะยังอยู่ สถานะกลับเป็น "กำลังดำเนินการ" และขั้นตอนถัดไปต้องยังไม่ส่งพิจารณา · บันทึกใน Audit Log และแจ้งกลุ่ม LINE</p>
      {error && <p role="alert" className="banner-error">{error}</p>}
      <div className={`field ${error && reason.trim().length < 3 ? "has-error" : ""}`}>
        <label htmlFor="revert-reason">เหตุผลที่ยกเลิก</label>
        <textarea id="revert-reason" rows={2} maxLength={1000} value={reason} onChange={(e) => setReason(e.target.value)} />
      </div>
      <div className="form-actions">
        <button type="button" className="ghost" disabled={busy} onClick={() => setOpen(false)}>ไม่ยกเลิก</button>
        <button type="button" className="danger" disabled={busy} onClick={() => void revert()}>{busy ? "กำลังยกเลิก…" : "ยืนยันยกเลิกขั้นตอน"}</button>
      </div>
    </div>
  );
}

/** อนุมัติ / ส่งกลับแก้ไข — ผู้เสนอรายการอนุมัติของตนเองไม่ได้ (SoD ตรวจที่ server) · ส่งกลับต้องระบุเหตุผล */
function DecisionPanel({ projectId, stepCode, onDone }: { projectId: number; stepCode: string; onDone: () => void }) {
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needReason, setNeedReason] = useState(false);

  async function decide(approve: boolean) {
    if (!approve && !comment.trim()) {
      setNeedReason(true);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api(`/api/projects/${projectId}/steps/${stepCode}/decision`, {
        method: "POST", body: JSON.stringify({ approve, comment: comment.trim() || null }),
      });
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? [err.message, ...err.violations.map((v) => v.message)].join(" — ") : "บันทึกผลไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="decision">
      <h4>พิจารณาอนุมัติ</h4>
      {error && <p role="alert" className="banner-error">{error}</p>}
      <div className={`field ${needReason && !comment.trim() ? "has-error" : ""}`}>
        <label htmlFor="decision-comment">ความเห็น (ต้องระบุเมื่อส่งกลับแก้ไข)</label>
        <textarea id="decision-comment" rows={2} maxLength={1000} value={comment} onChange={(e) => setComment(e.target.value)} />
        {needReason && !comment.trim() && <small role="alert" className="error">กรุณาระบุเหตุผลที่ส่งกลับแก้ไข</small>}
      </div>
      <div className="form-actions">
        <button type="button" className="ghost" disabled={busy} onClick={() => decide(false)}>ส่งกลับแก้ไข</button>
        <button type="button" disabled={busy} onClick={() => decide(true)}>{busy ? "กำลังบันทึก…" : "อนุมัติ"}</button>
      </div>
    </div>
  );
}

interface Person { personnel_id: number; full_name_th: string; position_th: string }
interface VendorHit { vendor_id: number; tax_id: string; name_th: string }

export function DynamicStepForm({ projectId, stepCode, canApprove, canRevert, onSubmitted }: Props) {
  const [form, setForm] = useState<StepFormResponse | null>(null);
  const [values, setValues] = useState<FormValues>({});
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const [serverErrors, setServerErrors] = useState<Violation[]>([]);
  const [banner, setBanner] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [people, setPeople] = useState<Person[]>([]);

  useEffect(() => {
    api<StepFormResponse>(`/api/projects/${projectId}/steps/${stepCode}/form`).then((f) => {
      setForm(f);
      setValues(f.values ?? {});
      if (f.fields.some((x) => x.type === "personnel_multi")) api<Person[]>("/api/personnel").then(setPeople);
    });
  }, [projectId, stepCode]);

  const clientErrors = useMemo(
    () => (form ? validateForm(form.fields, values, form.context) : {}),
    [form, values],
  );

  if (!form) return <p>กำลังโหลดแบบฟอร์ม…</p>;
  const locked = !["PENDING", "IN_PROGRESS", "REJECTED"].includes(form.step.status);

  const set = (name: string, v: FormValues[string]) => {
    setValues((prev) => ({ ...prev, [name]: v }));
    setServerErrors((prev) => prev.filter((e) => e.field !== name));
  };

  const errorFor = (spec: FieldSpec): string | undefined =>
    (touched[spec.name] ? clientErrors[spec.name] : undefined) ??
    serverErrors.find((e) => e.field === spec.name)?.message;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!form) return;
    setTouched(Object.fromEntries(form.fields.map((f) => [f.name, true])));
    if (Object.keys(clientErrors).length > 0) {
      setBanner("กรุณาแก้ไขข้อมูลที่ไม่ถูกต้องก่อนบันทึก");
      return;
    }
    setBusy(true);
    setBanner(null);
    try {
      await api(`/api/projects/${projectId}/steps/${stepCode}/submit`, {
        method: "POST",
        body: JSON.stringify({ data: toPayload(form.fields, values), row_version: form.row_version }),
      });
      onSubmitted();
    } catch (err) {
      if (err instanceof ApiError) {
        setServerErrors(err.violations);
        // ข้อผิดพลาดที่ไม่ผูกกับช่องใด (เช่น ลำดับขั้นตอน, SoD) แสดงเป็นแถบด้านบน
        const general = err.violations.filter((v) => !v.field).map((v) => v.message);
        setBanner([err.message, ...general].join(" — "));
      } else setBanner("เชื่อมต่อเซิร์ฟเวอร์ไม่ได้");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate className="step-form">
      <h3>{form.step.name_th}</h3>
      {form.step.legal_ref && <p className="legal">อ้างอิง: {form.step.legal_ref}</p>}
      {banner && <div role="alert" className="banner-error">{banner}</div>}

      {form.fields.filter((f) => isVisible(f, values)).map((spec) => {
        const err = errorFor(spec);
        const id = `f-${spec.name}`;
        return (
          <div key={spec.name} className={`field ${err ? "has-error" : ""}`}>
            <label htmlFor={id}>
              {spec.label_th}
              {(spec.required || spec.show_if) && spec.type !== "checkbox" && <span aria-hidden> *</span>}
            </label>
            <FieldInput
              id={id}
              spec={spec}
              value={values[spec.name]}
              disabled={locked}
              people={people}
              onChange={(v) => set(spec.name, v)}
              onBlur={() => setTouched((t) => ({ ...t, [spec.name]: true }))}
            />
            {spec.help_th && <small className="help">{spec.help_th}</small>}
            {err && <small role="alert" className="error">{err}</small>}
          </div>
        );
      })}

      {!locked && (
        <button type="submit" disabled={busy}>{busy ? "กำลังบันทึก…" : "บันทึกและส่งพิจารณา"}</button>
      )}
      {form.step.status === "SUBMITTED" && (canApprove
        ? <DecisionPanel projectId={projectId} stepCode={stepCode} onDone={onSubmitted} />
        : <p className="muted small">ส่งพิจารณาแล้ว — รอหัวหน้าเจ้าหน้าที่หรือผู้มีอำนาจอนุมัติ</p>)}
      {canRevert && (form.step.status === "SUBMITTED" || form.step.status === "APPROVED") && stepCode !== "CREATE_PROJECT" && (
        <RevertPanel projectId={projectId} stepCode={stepCode} status={form.step.status} onDone={onSubmitted} />
      )}
    </form>
  );
}

interface InputProps {
  id: string;
  spec: FieldSpec;
  value: FormValues[string];
  disabled: boolean;
  people: Person[];
  onChange: (v: FormValues[string]) => void;
  onBlur: () => void;
}

function FieldInput({ id, spec, value, disabled, people, onChange, onBlur }: InputProps) {
  const common = { id, disabled, onBlur };
  switch (spec.type) {
    case "textarea":
      return <textarea {...common} rows={4} maxLength={spec.max_length}
                       value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)} />;
    case "select":
      return (
        <select {...common} value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)}>
          <option value="">— เลือก —</option>
          {spec.options?.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      );
    case "checkbox":
      return <input {...common} type="checkbox" checked={value === true} onChange={(e) => onChange(e.target.checked)} />;
    case "integer":
      return <input {...common} type="number" inputMode="numeric" step={1} min={spec.min} max={spec.max}
                    value={value === undefined ? "" : String(value)}
                    onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))} />;
    case "money":
    case "percent":
      // เก็บเป็น string ตามที่พิมพ์ (ไม่แปลงเป็น number) เพื่อส่งให้ backend เป็น Decimal ตรงตัว
      return <input {...common} type="text" inputMode="decimal" placeholder="0.00"
                    value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value.replace(/,/g, ""))} />;
    case "date":
      return <input {...common} type="date" value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)} />;
    case "tax_id":
      return <input {...common} type="text" inputMode="numeric" maxLength={13} placeholder="เลข 13 หลัก"
                    value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value.replace(/\D/g, ""))} />;
    case "personnel_multi":
      return <PersonnelPicker {...common} people={people} value={(value as number[]) ?? []} onChange={onChange} />;
    case "vendor_multi":
      return <VendorPicker value={(value as number[]) ?? []} disabled={disabled} onChange={onChange} />;
    default:
      return <input {...common} type="text" maxLength={spec.max_length}
                    value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)} />;
  }
}

/** เลือกกรรมการตามลำดับ: คนแรก = ประธาน (ตรงกับการจัดลำดับในคำสั่งแต่งตั้ง) */
function PersonnelPicker({ people, value, disabled, onChange, onBlur }: {
  people: Person[]; value: number[]; disabled: boolean; onChange: (v: number[]) => void; onBlur: () => void;
}) {
  const toggle = (pid: number) =>
    onChange(value.includes(pid) ? value.filter((x) => x !== pid) : [...value, pid]);
  return (
    <ul className="picker" onBlur={onBlur}>
      {people.map((p) => {
        const idx = value.indexOf(p.personnel_id);
        return (
          <li key={p.personnel_id}>
            <label>
              <input type="checkbox" disabled={disabled} checked={idx >= 0} onChange={() => toggle(p.personnel_id)} />
              {p.full_name_th} — {p.position_th}
              {idx >= 0 && <em> ({value.length === 1 ? "ผู้ตรวจรับ" : idx === 0 ? "ประธาน" : "กรรมการ"})</em>}
            </label>
          </li>
        );
      })}
    </ul>
  );
}

function VendorPicker({ value, disabled, onChange }: {
  value: number[]; disabled: boolean; onChange: (v: number[]) => void;
}) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<VendorHit[]>([]);
  const [chosen, setChosen] = useState<VendorHit[]>([]);

  useEffect(() => {
    if (q.trim().length < 2) return setHits([]);
    const t = setTimeout(() => api<VendorHit[]>(`/api/vendors?q=${encodeURIComponent(q)}`).then(setHits), 300);
    return () => clearTimeout(t);
  }, [q]);

  const add = (v: VendorHit) => {
    if (value.includes(v.vendor_id)) return;
    setChosen([...chosen, v]);
    onChange([...value, v.vendor_id]);
  };
  const remove = (id: number) => {
    setChosen(chosen.filter((c) => c.vendor_id !== id));
    onChange(value.filter((x) => x !== id));
  };

  return (
    <div className="vendor-picker">
      <ul>
        {chosen.map((c) => (
          <li key={c.vendor_id}>
            {c.name_th} ({c.tax_id})
            {!disabled && <button type="button" onClick={() => remove(c.vendor_id)}>ลบ</button>}
          </li>
        ))}
      </ul>
      {!disabled && (
        <>
          <input type="search" placeholder="ค้นหาชื่อหรือเลขผู้เสียภาษี" value={q} onChange={(e) => setQ(e.target.value)} />
          <ul>{hits.map((h) => <li key={h.vendor_id}><button type="button" onClick={() => add(h)}>+ {h.name_th}</button></li>)}</ul>
        </>
      )}
    </div>
  );
}
