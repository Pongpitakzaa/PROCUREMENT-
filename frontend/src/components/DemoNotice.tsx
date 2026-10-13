/** ส่วนแสดงผลของเวอร์ชันสาธิตบนเว็บ (แสดงเฉพาะ build โหมด demo) */
import { useState } from "react";
import { DEMO_PASSWORD, DEMO_STORAGE_KEY, DEMO_USERS } from "../demo/accounts";

export function DemoAccounts({ onPick }: { onPick: (username: string) => void }) {
  return (
    <div className="demo-accounts">
      <p className="demo-title">เวอร์ชันสาธิต — เลือกบทบาทเพื่อเข้าสู่ระบบ</p>
      <div className="demo-grid">
        {DEMO_USERS.map((u) => (
          <button key={u.username} type="button" className="demo-user" onClick={() => onPick(u.username)}>
            <strong>{u.role}</strong>
            <small>{u.hint}</small>
          </button>
        ))}
      </div>
      <p className="muted small">หรือพิมพ์ชื่อผู้ใช้ {DEMO_USERS.map((u) => u.username).join(" / ")} รหัสผ่าน <code>{DEMO_PASSWORD}</code></p>
    </div>
  );
}

export function DemoBanner() {
  const [confirming, setConfirming] = useState(false);
  const reset = () => {
    try {
      localStorage.removeItem(DEMO_STORAGE_KEY);
    } catch {
      /* ignore */
    }
    location.reload();
  };
  return (
    <p className="demo-banner">
      ระบบทดลองบนเว็บ · ข้อมูลตัวอย่าง ไม่ใช่ข้อมูลจริงของหน่วยงาน · ข้อมูลที่บันทึกเก็บไว้ในเบราว์เซอร์นี้เท่านั้น{" "}
      {confirming ? (
        <>
          <button type="button" className="demo-reset" onClick={reset}>ยืนยันล้างข้อมูล</button>
          <button type="button" className="demo-reset ghost" onClick={() => setConfirming(false)}>ยกเลิก</button>
        </>
      ) : (
        <button type="button" className="demo-reset ghost" onClick={() => setConfirming(true)}>เริ่มใหม่จากข้อมูลตัวอย่าง</button>
      )}
    </p>
  );
}
