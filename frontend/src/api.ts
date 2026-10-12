import type { Violation } from "./types";

/**
 * เก็บ access token ไว้ใน memory เท่านั้น (ไม่ใช้ localStorage) — ถ้ามี XSS หลุดมา
 * สคริปต์ก็อ่าน token จาก storage ไม่ได้; ปิดแท็บแล้วต้อง login ใหม่ (token อายุ 15 นาที)
 */
let accessToken: string | null = null;

export class ApiError extends Error {
  constructor(public status: number, message: string, public violations: Violation[] = []) {
    super(message);
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");

  let res: Response;
  try {
    res = await fetch(path, { ...init, headers, credentials: "same-origin" });
  } catch {
    // มือถือเสียสัญญาณบ่อย — แจ้งเป็นข้อความที่ผู้ใช้เข้าใจแทน "Failed to fetch"
    throw new ApiError(0, navigator.onLine === false
      ? "ไม่มีการเชื่อมต่ออินเทอร์เน็ต — ข้อมูลยังไม่ถูกบันทึก กรุณาลองใหม่เมื่อกลับมาออนไลน์"
      : "ติดต่อเซิร์ฟเวอร์ไม่ได้ กรุณาลองใหม่อีกครั้ง", []);
  }
  if (res.status === 401) accessToken = null;
  if (!res.ok) {
    const body = await res.json().catch(() => ({ message: `HTTP ${res.status}`, violations: [] }));
    throw new ApiError(res.status, body.message, body.violations ?? []);
  }
  const type = res.headers.get("content-type") ?? "";
  return (type.includes("application/json") ? res.json() : res.blob()) as Promise<T>;
}

export async function login(username: string, password: string): Promise<void> {
  const r = await api<{ access_token: string }>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  accessToken = r.access_token;
}

export const isLoggedIn = () => accessToken !== null;

/** ใช้หลังเปลี่ยนรหัสผ่าน: token เดิมถูกยกเลิกโดยเซิร์ฟเวอร์ จึงต้องแทนด้วย token ใหม่ */
export function setAccessToken(token: string): void {
  accessToken = token;
}

export function logout(): void {
  accessToken = null;
}

/** บันทึก Blob เป็นไฟล์ในเครื่องผู้ใช้ */
function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  document.body.append(a);   // Firefox ต้องอยู่ใน DOM
  a.click();
  a.remove();
  // iOS Safari อ่าน blob หลัง click แบบ async — ถ้า revoke ทันทีจะได้ไฟล์ว่าง/ไม่เปิดหน้าตัวอย่าง
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

/** ดาวน์โหลดเอกสาร (DOCX/PDF/XLSX) โดยไม่เปิดหน้าใหม่ */
export async function exportDocument(projectId: number, stepCode: string, format: "docx" | "pdf" | "xlsx") {
  const blob = await api<Blob>(`/api/projects/${projectId}/steps/${stepCode}/export?format=${format}`, {
    method: "POST",
  });
  saveBlob(blob, `${stepCode}.${format}`);
}

/** ดาวน์โหลดรายงานสรุป Excel ของ Dashboard */
export async function downloadDashboardReport(fiscalYear: number) {
  const blob = await api<Blob>(`/api/dashboard/report.xlsx?fiscal_year=${fiscalYear}`);
  saveBlob(blob, `procurement-${fiscalYear}.xlsx`);
}
