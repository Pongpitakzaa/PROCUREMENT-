/** เปลี่ยนรหัสผ่านของตนเอง — ตรวจนโยบายแบบ real-time; สำเร็จแล้วได้ token ใหม่ (token เดิมถูกยกเลิก) */
import { useEffect, useRef, useState } from "react";
import { ApiError, api, setAccessToken } from "../api";
import { passwordProblems } from "../userValidation";

export function ChangePasswordDialog({ username, onClose }: { username: string; onClose: (changed: boolean) => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    ref.current?.showModal();   // <dialog> จัดการโฟกัสและปุ่ม Esc ให้เอง
  }, []);

  const problems = next ? passwordProblems(next, username) : [];
  const mismatch = confirm.length > 0 && confirm !== next;
  const ready = current && next && !problems.length && confirm === next && next !== current;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!ready) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ access_token: string }>("/api/auth/change-password", {
        method: "POST", body: JSON.stringify({ current_password: current, new_password: next }),
      });
      setAccessToken(r.access_token);
      onClose(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "เปลี่ยนรหัสผ่านไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  return (
    <dialog ref={ref} className="dialog card" onClose={() => onClose(false)} aria-labelledby="cp-title">
      <form onSubmit={submit} noValidate>
        <h3 id="cp-title">เปลี่ยนรหัสผ่าน</h3>
        <div className="field">
          <label htmlFor="cp-current">รหัสผ่านปัจจุบัน</label>
          <input id="cp-current" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
        </div>
        <div className={`field ${problems.length ? "has-error" : ""}`}>
          <label htmlFor="cp-new">รหัสผ่านใหม่</label>
          <input id="cp-new" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
          <ul className="pw-rules">
            {["ต้องยาวอย่างน้อย 12 ตัวอักษร", "ต้องมีทั้งตัวอักษรและตัวเลข", "ห้ามมีชื่อผู้ใช้อยู่ในรหัสผ่าน"].map((rule) => (
              <li key={rule} className={!next ? "" : problems.includes(rule) ? "bad" : "good"}>{rule}</li>
            ))}
            {next && next === current && <li className="bad">รหัสผ่านใหม่ต้องไม่ซ้ำรหัสผ่านเดิม</li>}
          </ul>
        </div>
        <div className={`field ${mismatch ? "has-error" : ""}`}>
          <label htmlFor="cp-confirm">ยืนยันรหัสผ่านใหม่</label>
          <input id="cp-confirm" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
          {mismatch && <small className="error">รหัสผ่านไม่ตรงกัน</small>}
        </div>
        {error && <p role="alert" className="banner-error">{error}</p>}
        <div className="form-actions">
          <button type="button" className="ghost" onClick={() => ref.current?.close()}>ยกเลิก</button>
          <button type="submit" disabled={!ready || busy}>{busy ? "กำลังบันทึก…" : "เปลี่ยนรหัสผ่าน"}</button>
        </div>
      </form>
    </dialog>
  );
}
