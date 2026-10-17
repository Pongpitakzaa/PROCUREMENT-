/** คำนำหน้าชื่อที่เลือกได้ในระบบ — ทั่วไป และคำย่อยศทหารอากาศ (พันจ่าอากาศตรี ถึง นาวาอากาศเอก) */
export const TITLE_GROUPS: { label: string; titles: { value: string; full?: string }[] }[] = [
  { label: "ทั่วไป", titles: [{ value: "นาย" }, { value: "นาง" }, { value: "นางสาว" }] },
  { label: "ยศทหารอากาศ (ชั้นประทวน)", titles: [
    { value: "พ.อ.ต.", full: "พันจ่าอากาศตรี" },
    { value: "พ.อ.ท.", full: "พันจ่าอากาศโท" },
    { value: "พ.อ.อ.", full: "พันจ่าอากาศเอก" },
  ] },
  { label: "ยศทหารอากาศ (ชั้นสัญญาบัตร)", titles: [
    { value: "ร.ต.", full: "เรืออากาศตรี" },
    { value: "ร.ท.", full: "เรืออากาศโท" },
    { value: "ร.อ.", full: "เรืออากาศเอก" },
    { value: "น.ต.", full: "นาวาอากาศตรี" },
    { value: "น.ท.", full: "นาวาอากาศโท" },
    { value: "น.อ.", full: "นาวาอากาศเอก" },
  ] },
];

export const ALL_TITLES = TITLE_GROUPS.flatMap((g) => g.titles.map((t) => t.value));

/** ตัวอักษรแรกของชื่อ (ตัดคำนำหน้า/ยศออก) สำหรับ avatar */
export function initialOf(fullName: string): string {
  const sorted = [...ALL_TITLES].sort((a, b) => b.length - a.length);
  let name = fullName.trim();
  for (const t of sorted) {
    if (name.startsWith(t)) { name = name.slice(t.length).trim(); break; }
  }
  return name.charAt(0);
}
