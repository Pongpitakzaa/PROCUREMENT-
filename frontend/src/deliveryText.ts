/** ข้อความกำหนดส่งมอบ (ใช้ร่วมกันหน้ารายการโครงการและหน้าผู้ดูแล) */
const TH_MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."];

export function thaiDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  return `${d} ${TH_MONTHS[m - 1]} ${y + 543}`;
}

export function dueLabel(daysLeft: number): string {
  if (daysLeft < 0) return `เลยกำหนด ${-daysLeft} วัน`;
  if (daysLeft === 0) return "ครบกำหนดวันนี้";
  if (daysLeft === 1) return "พรุ่งนี้";
  return `อีก ${daysLeft} วัน`;
}
