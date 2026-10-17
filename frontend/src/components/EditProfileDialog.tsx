/** แก้ไขข้อมูลส่วนตัวของตนเอง: คำนำหน้า ชื่อ นามสกุล ตำแหน่ง ประเภทบุคลากร (เลขบัตร/หน่วยงาน/บทบาท แก้ได้เฉพาะผู้ดูแล) */
import { useEffect, useRef, useState } from "react";
import { ApiError, api } from "../api";
import { TITLE_GROUPS } from "../titles";
import type { Me, MyProfile } from "../types";

export const EMPLOYMENT_TH: Record<MyProfile["employment_type"], string> = {
  CIVIL_SERVANT: "ข้าราชการ", GOV_EMPLOYEE: "พนักงานราชการ", PERMANENT_EMPLOYEE: "ลูกจ้างประจำ",
  STATE_OFFICIAL: "เจ้าหน้าที่ของรัฐอื่น", OTHER: "อื่น ๆ",
};

export function EditProfileDialog({ me, onClose }: { me: Me; onClose: (updated: Me | null) => void }) {
  const [draft, setDraft] = useState<MyProfile>({ ...me.profile });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { ref.current?.showModal(); }, []);

  const set = <K extends keyof MyProfile>(k: K, v: MyProfile[K]) => setDraft((d) => ({ ...d, [k]: v }));
  const changed = (Object.keys(draft) as (keyof MyProfile)[]).filter((k) => k !== "department_name_th" && draft[k] !== me.profile[k]);
  const invalid = !draft.first_name_th.trim() || !draft.last_name_th.trim() || !draft.position_th.trim();
  const ready = changed.length > 0 && !invalid;
  const titleKnown = TITLE_GROUPS.some((g) => g.titles.some((t) => t.value === draft.title_th));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!ready) return;
    setBusy(true); setError(null);
    try {
      const body = Object.fromEntries(changed.map((k) => [k, typeof draft[k] === "string" ? String(draft[k]).trim() : draft[k]]));
      const updated = await api<Me>("/api/auth/me/profile", { method: "PATCH", body: JSON.stringify(body) });
      onClose(updated);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "บันทึกไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  return (
    <dialog ref={ref} className="dialog card" onClose={() => onClose(null)} aria-labelledby="ep-title">
      <form onSubmit={submit} noValidate>
        <h3 id="ep-title">แก้ไขข้อมูลส่วนตัว</h3>
        <p className="muted small">หน่วยงาน {me.profile.department_name_th} · ชื่อผู้ใช้ {me.username} — เปลี่ยนหน่วยงาน เลขประจำตัวประชาชน หรือบทบาท ต้องให้ผู้ดูแลระบบทำ</p>
        <div className="name-row">
          <div className="field">
            <label htmlFor="ep-title_th">คำนำหน้า</label>
            <select id="ep-title_th" value={draft.title_th} onChange={(e) => set("title_th", e.target.value)}>
              {!titleKnown && <option value={draft.title_th}>{draft.title_th}</option>}
              {TITLE_GROUPS.map((g) => (
                <optgroup key={g.label} label={g.label}>
                  {g.titles.map((t) => <option key={t.value} value={t.value}>{t.full ? `${t.value} (${t.full})` : t.value}</option>)}
                </optgroup>
              ))}
            </select>
          </div>
          <div className={`field ${!draft.first_name_th.trim() ? "has-error" : ""}`}>
            <label htmlFor="ep-first">ชื่อ</label>
            <input id="ep-first" maxLength={100} value={draft.first_name_th} onChange={(e) => set("first_name_th", e.target.value)} />
          </div>
          <div className={`field ${!draft.last_name_th.trim() ? "has-error" : ""}`}>
            <label htmlFor="ep-last">นามสกุล</label>
            <input id="ep-last" maxLength={100} value={draft.last_name_th} onChange={(e) => set("last_name_th", e.target.value)} />
          </div>
        </div>
        <div className={`field ${!draft.position_th.trim() ? "has-error" : ""}`}>
          <label htmlFor="ep-position">ตำแหน่ง</label>
          <input id="ep-position" maxLength={150} value={draft.position_th} onChange={(e) => set("position_th", e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="ep-employment">ประเภทบุคลากร</label>
          <select id="ep-employment" value={draft.employment_type} onChange={(e) => set("employment_type", e.target.value as MyProfile["employment_type"])}>
            {Object.entries(EMPLOYMENT_TH).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>
        {error && <p role="alert" className="banner-error">{error}</p>}
        <div className="form-actions">
          <button type="button" className="ghost" onClick={() => ref.current?.close()}>ยกเลิก</button>
          <button type="submit" disabled={!ready || busy}>{busy ? "กำลังบันทึก…" : "บันทึก"}</button>
        </div>
      </form>
    </dialog>
  );
}
