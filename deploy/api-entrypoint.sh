#!/bin/sh
# ฟอนต์ที่หน่วยงานติดตั้งเพิ่ม (เช่น TH Sarabun New จาก deploy/fonts/) ต้องเข้า cache ก่อน LibreOffice ใช้งาน
set -e
if [ -n "$(ls -A /usr/local/share/fonts/agency 2>/dev/null)" ]; then
  fc-cache -f /usr/local/share/fonts/agency >/dev/null 2>&1 || true
fi
# ตรวจค่าตั้งที่จำเป็นก่อน — ให้ข้อความที่อ่านเข้าใจแทน traceback (เช่น สร้าง service บน Render เองโดยไม่ใช้ Blueprint)
missing=""
[ -n "${PROC_DATABASE_URL:-}" ] || missing="$missing PROC_DATABASE_URL"
[ -n "${PROC_JWT_SECRET:-}" ] || missing="$missing PROC_JWT_SECRET"
[ -n "${PROC_BLIND_INDEX_KEY:-}" ] || missing="$missing PROC_BLIND_INDEX_KEY"
[ -n "${PROC_DATA_KEYS:-}${PROC_DATA_KEY:-}" ] || missing="$missing PROC_DATA_KEY"
[ -n "${PROC_BACKUP_KEY:-}" ] || missing="$missing PROC_BACKUP_KEY"
if [ -n "$missing" ]; then
  echo "ผิดพลาด: ยังไม่ได้ตั้งค่า:$missing" >&2
  echo "  Render: สร้างด้วย Blueprint (New → Blueprint → เลือก repository นี้) ระบบจะสร้างฐานข้อมูลและค่าลับให้ — ดู deploy/RENDER.md" >&2
  echo "  Docker Compose: ติดตั้งด้วย deploy/install.sh ซึ่งสร้างไฟล์ .env ให้" >&2
  exit 1
fi

# สร้าง/ปรับฐานข้อมูลอัตโนมัติ (รันซ้ำได้): schema เมื่อฐานข้อมูลว่าง + migration + ผู้ดูแลคนแรกจาก PROC_BOOTSTRAP_*
# ปิดได้ด้วย PROC_AUTO_INIT_DB=0
if [ "${PROC_AUTO_INIT_DB:-1}" = "1" ]; then
  python -m app.cli init-db
fi
exec "$@"
