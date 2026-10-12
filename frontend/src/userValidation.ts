/**
 * กฎผู้ใช้ฝั่ง client — สะท้อน backend/app/core/security.py (password_problems / role_combination_problems)
 */
import type { RoleCode } from "./types";

export const PASSWORD_MIN_LENGTH = 12;

export function passwordProblems(password: string, username = ""): string[] {
  const p: string[] = [];
  if (password.length < PASSWORD_MIN_LENGTH) p.push(`ต้องยาวอย่างน้อย ${PASSWORD_MIN_LENGTH} ตัวอักษร`);
  if (!/\p{L}/u.test(password) || !/\d/.test(password)) p.push("ต้องมีทั้งตัวอักษรและตัวเลข");
  if (username && password.toLowerCase().includes(username.toLowerCase())) p.push("ห้ามมีชื่อผู้ใช้อยู่ในรหัสผ่าน");
  return p;
}

const PROCUREMENT: RoleCode[] = ["PROCUREMENT_OFFICER", "HEAD_OF_PROCUREMENT", "EXECUTIVE"];

export function roleProblems(roles: RoleCode[]): string[] {
  const p: string[] = [];
  if (roles.length === 0) p.push("ต้องมีอย่างน้อย 1 บทบาท");
  if (roles.includes("ADMIN") && roles.some((r) => PROCUREMENT.includes(r)))
    p.push("ผู้ดูแลระบบห้ามมีบทบาทในงานพัสดุ");
  if (roles.includes("AUDITOR") && roles.length > 1) p.push("ผู้ตรวจสอบภายในต้องมีบทบาทเดียว");
  return p;
}

export const USERNAME_RE = /^[a-z0-9_.-]{3,60}$/;
