/** ส่วนประกอบสำหรับใช้งานแบบแอปบนมือถือ: ปุ่มติดตั้ง, วิธีติดตั้งบน iOS, แถบสถานะออฟไลน์/อัปเดต */
import { useEffect, useRef, useState } from "react";
import { applyUpdate, promptInstall, usePwa } from "../pwa";

/** iOS ไม่มีปุ่มติดตั้งอัตโนมัติ — บอกขั้นตอนผ่านเมนูแชร์ของ Safari */
function IosInstallDialog({ onClose }: { onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { ref.current?.showModal(); }, []);
  return (
    <dialog ref={ref} className="dialog card" onClose={onClose} aria-labelledby="ios-install-title">
      <h3 id="ios-install-title">ติดตั้งแอปบน iPhone / iPad</h3>
      <ol className="install-steps">
        <li>เปิดหน้านี้ด้วย <b>Safari</b></li>
        <li>แตะปุ่ม <b>แชร์</b> <span className="share-glyph" aria-hidden>⬆︎</span> ที่แถบด้านล่าง (iPad: มุมขวาบน)</li>
        <li>เลือก <b>เพิ่มไปยังหน้าจอโฮม</b> แล้วแตะ <b>เพิ่ม</b></li>
      </ol>
      <p className="muted small">แอปจะเปิดเต็มจอจากไอคอน “จัดซื้อจัดจ้าง” — ข้อมูลราชการไม่ถูกเก็บไว้ในเครื่อง ต้องเข้าสู่ระบบทุกครั้งที่เปิดแอปใหม่</p>
      <div className="form-actions">
        <button type="button" onClick={() => ref.current?.close()}>เข้าใจแล้ว</button>
      </div>
    </dialog>
  );
}

/** ปุ่ม/เมนู "ติดตั้งแอป" — แสดงเฉพาะเมื่อติดตั้งได้ (ซ่อนเมื่อเปิดจากไอคอนบนหน้าจอโฮมแล้ว) */
export function InstallButton({ className, role, onBeforeOpen }: { className?: string; role?: string; onBeforeOpen?: () => void }) {
  const { install } = usePwa();
  const [showIos, setShowIos] = useState(false);
  if (install === "none") return null;
  return (
    <>
      <button type="button" className={className} role={role} onClick={() => {
        onBeforeOpen?.();
        if (install === "ios") setShowIos(true);
        else void promptInstall();
      }}>
        📲 ติดตั้งแอปบนมือถือ
      </button>
      {showIos && <IosInstallDialog onClose={() => setShowIos(false)} />}
    </>
  );
}

/** แถบสถานะด้านบน: ออฟไลน์ / มีเวอร์ชันใหม่ */
export function AppStatusBar() {
  const { online, updateReady } = usePwa();
  if (!online) {
    return <p role="status" className="app-status offline">ออฟไลน์ — ดูหน้าที่เปิดอยู่ได้ แต่บันทึก/ดึงข้อมูลไม่ได้จนกว่าจะกลับมาออนไลน์</p>;
  }
  if (updateReady) {
    return (
      <p role="status" className="app-status update">
        มีระบบเวอร์ชันใหม่ <button type="button" onClick={applyUpdate}>อัปเดตตอนนี้</button>
        <span className="muted small"> (บันทึกงานที่กรอกค้างไว้ก่อน)</span>
      </p>
    );
  }
  return null;
}
