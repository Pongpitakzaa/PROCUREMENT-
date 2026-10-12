const PROJECT_STATUS_TH: Record<string, string> = {
  DRAFT: "ร่าง",
  IN_PROGRESS: "กำลังดำเนินการ",
  AWARDED: "ได้ผู้ชนะแล้ว",
  CONTRACTED: "ลงนามสัญญาแล้ว",
  COMPLETED: "เสร็จสิ้น",
  CANCELLED: "ยกเลิก",
};

export const PROJECT_STATUSES = Object.keys(PROJECT_STATUS_TH);

export function projectStatusTh(status: string): string {
  return PROJECT_STATUS_TH[status] ?? status;
}

export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge badge-${status.toLowerCase()}`}>{projectStatusTh(status)}</span>;
}
