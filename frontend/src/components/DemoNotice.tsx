/** ส่วนแสดงผลของเวอร์ชันสาธิตบนเว็บ (แสดงเฉพาะ build โหมด demo) */
import { DEMO_PASSWORD, DEMO_USERS } from "../demo/accounts";

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
  return (
    <p className="demo-banner">
      เวอร์ชันสาธิต · ข้อมูลตัวอย่างทั้งหมด ไม่ใช่ข้อมูลจริงของหน่วยงาน · บันทึกได้แต่จะกลับเป็นค่าเริ่มต้นเมื่อโหลดหน้าใหม่
    </p>
  );
}
