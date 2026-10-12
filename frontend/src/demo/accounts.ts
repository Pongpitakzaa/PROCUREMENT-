/** บัญชีของเวอร์ชันสาธิต (แยกไฟล์จาก mockServer เพื่อไม่ให้ข้อมูลตัวอย่างหลุดเข้า build ปกติ) */
export const IS_DEMO = import.meta.env.VITE_DEMO === "1";
export const DEMO_PASSWORD = "Demo@1234";
export const DEMO_USERS = [
  { username: "officer", role: "เจ้าหน้าที่พัสดุ", hint: "สร้างโครงการ กรอกขั้นตอน ทะเบียนผู้ประกอบการ" },
  { username: "head", role: "หัวหน้าเจ้าหน้าที่", hint: "อนุมัติขั้นตอน บันทึกผู้ทิ้งงาน" },
  { username: "director", role: "ผู้บริหาร", hint: "อนุมัติสั่งซื้อ ดู Dashboard" },
  { username: "admin", role: "ผู้ดูแลระบบ", hint: "ผู้ใช้ แบบฟอร์ม Audit log" },
] as const;
